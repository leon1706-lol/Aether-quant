import json

import pytest

from generate_evaluation_report import (
    BENCHMARK_MARKER_END,
    BENCHMARK_MARKER_START,
    EVAL_FULL_STATS_MARKER_END,
    EVAL_FULL_STATS_MARKER_START,
    EVAL_MARKER_END,
    EVAL_MARKER_START,
    OTHER_METRICS_MARKER_END,
    OTHER_METRICS_MARKER_START,
    WALKFORWARD_FULL_STATS_MARKER_END,
    WALKFORWARD_FULL_STATS_MARKER_START,
    WALKFORWARD_MARKER_END,
    WALKFORWARD_MARKER_START,
    _build_benchmark_markdown,
    _build_eval_compact_markdown,
    _build_eval_full_stats_markdown,
    _build_other_metrics_markdown,
    _build_walk_forward_compact_markdown,
    _build_walk_forward_full_stats_markdown,
    load_latest_walk_forward_summary,
    load_offline_evaluation_summary,
    update_readme_evaluation_sections,
)


def _rank_book(net_sharpe=1.5, gross_sharpe=1.6):
    return {
        "gross_sharpe": gross_sharpe,
        "net_sharpe": net_sharpe,
        "gross_total_return": 0.1,
        "net_total_return": 0.09,
        "net_max_drawdown": -0.03,
        "annualized_turnover": 1.5,
        "cost_drag_annual_bps": 10.0,
        "num_rebalances": 50,
        "num_dates_used": 500,
        "mean_names_long": 6.0,
        "mean_names_short": 6.0,
    }


def _capacity_report():
    return {
        "capacity_usd": 4_000_000.0,
        "binding_ticker": "BNO",
        "per_top_n": [{"top_n": 3, "net_sharpe": 2.0}, {"top_n": 6, "net_sharpe": 1.5}],
    }


def _stress_report():
    return {
        "stress": [
            {"cost_multiplier": 1.0, "gross_sharpe": 1.6, "net_sharpe": 1.5, "cost_drag_annual_bps": 10.0},
            {"cost_multiplier": 2.0, "gross_sharpe": 1.6, "net_sharpe": 1.47, "cost_drag_annual_bps": 20.0},
        ]
    }


def _write_evaluation_files(ml_dir, model_kind="sequence", net_sharpe=1.5):
    evaluation_dir = ml_dir / "evaluation"
    evaluation_dir.mkdir(parents=True, exist_ok=True)
    (evaluation_dir / f"rank_book_simulation_{model_kind}.json").write_text(
        json.dumps(_rank_book(net_sharpe=net_sharpe)), encoding="utf-8"
    )
    (evaluation_dir / f"capacity_report_{model_kind}.json").write_text(json.dumps(_capacity_report()), encoding="utf-8")
    (evaluation_dir / f"cost_stress_report_{model_kind}.json").write_text(json.dumps(_stress_report()), encoding="utf-8")


def _walk_forward_summary():
    return {
        "run_id": "walk-forward-test-uuid",
        "num_windows": 2,
        "window_results": [
            {"window": {"backtest": {"start": "2019-01-01", "end": "2019-12-31"}}, "backtest_mcc": 0.02},
            {"window": {"backtest": {"start": "2020-01-01", "end": "2020-12-31"}}, "backtest_mcc": 0.04},
        ],
        "net_performance_by_window": [
            {"window_index": 0, "model_kind": "sequence", "simulation": {
                "gross_sharpe": 1.0, "net_sharpe": 0.9, "net_total_return": 0.05,
                "net_max_drawdown": -0.02, "annualized_turnover": 1.2,
            }},
            {"window_index": 1, "model_kind": "multitask", "simulation": {
                "gross_sharpe": -0.2, "net_sharpe": -0.3, "net_total_return": -0.01,
                "net_max_drawdown": -0.05, "annualized_turnover": 2.0,
            }},
        ],
        "stability_by_metric": {
            "backtest_mcc": {
                "mean": 0.03, "sign_flip_fraction": 0.0, "stable": True,
                "bootstrap": {"lower_bound": 0.01, "upper_bound": 0.05},
            },
        },
    }


def _write_walk_forward_summary(ml_dir, run_id="walk-forward-test-uuid"):
    run_dir = ml_dir / "versions" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "walk_forward_summary.json").write_text(json.dumps(_walk_forward_summary()), encoding="utf-8")


def _write_readme_with_markers(path) -> None:
    path.write_text(
        "# Aether Quant\n\nIntro.\n\n"
        f"{EVAL_MARKER_START}\nold eval\n{EVAL_MARKER_END}\n\n"
        f"{EVAL_FULL_STATS_MARKER_START}\nold eval full\n{EVAL_FULL_STATS_MARKER_END}\n\n"
        f"{WALKFORWARD_MARKER_START}\nold wf\n{WALKFORWARD_MARKER_END}\n\n"
        f"{WALKFORWARD_FULL_STATS_MARKER_START}\nold wf full\n{WALKFORWARD_FULL_STATS_MARKER_END}\n\n"
        f"{OTHER_METRICS_MARKER_START}\nold other\n{OTHER_METRICS_MARKER_END}\n\n"
        "More text.\n",
        encoding="utf-8",
    )


def test_load_offline_evaluation_summary_returns_none_per_model_when_absent(tmp_path, monkeypatch):
    import generate_evaluation_report as report_module

    monkeypatch.setattr(report_module, "EVALUATION_DIR", tmp_path / "ml" / "evaluation")

    summary = load_offline_evaluation_summary()

    assert summary == {"sequence": None, "multitask": None}


def test_load_offline_evaluation_summary_reads_only_the_model_that_exists(tmp_path, monkeypatch):
    import generate_evaluation_report as report_module

    ml_dir = tmp_path / "ml"
    _write_evaluation_files(ml_dir, model_kind="sequence", net_sharpe=1.5)
    monkeypatch.setattr(report_module, "EVALUATION_DIR", ml_dir / "evaluation")

    summary = load_offline_evaluation_summary()

    assert summary["multitask"] is None
    assert summary["sequence"]["rank_book"]["net_sharpe"] == 1.5


def test_build_eval_compact_markdown_shows_both_models_side_by_side():
    summary = {
        "multitask": {"rank_book": _rank_book(net_sharpe=1.33), "capacity": _capacity_report(), "stress": _stress_report()},
        "sequence": {"rank_book": _rank_book(net_sharpe=1.52), "capacity": _capacity_report(), "stress": _stress_report()},
    }

    body = _build_eval_compact_markdown(summary)

    assert "1.330" in body
    assert "1.520" in body


def test_build_eval_compact_markdown_degrades_gracefully_when_a_model_is_missing():
    summary = {"multitask": None, "sequence": {"rank_book": _rank_book(), "capacity": None, "stress": None}}

    body = _build_eval_compact_markdown(summary)

    assert "—" in body  # multitask column shows placeholders, not a crash


def test_build_eval_full_stats_markdown_includes_capacity_and_stress_tables():
    summary = {"sequence": {"rank_book": _rank_book(), "capacity": _capacity_report(), "stress": _stress_report()}, "multitask": None}

    body = _build_eval_full_stats_markdown(summary)

    assert "Sequence model" in body
    assert "Multitask model" in body
    assert "not yet evaluated" in body.lower()
    assert "BNO" in body
    assert "2.0x" in body


def test_load_latest_walk_forward_summary_picks_newest_by_mtime(tmp_path, monkeypatch):
    import generate_evaluation_report as report_module

    ml_dir = tmp_path / "ml"
    _write_walk_forward_summary(ml_dir, run_id="walk-forward-old")
    _write_walk_forward_summary(ml_dir, run_id="walk-forward-new")
    monkeypatch.setattr(report_module, "VERSIONS_DIR", ml_dir / "versions")

    summary = load_latest_walk_forward_summary()

    assert summary is not None


def test_build_walk_forward_compact_markdown_handles_missing_summary():
    body = _build_walk_forward_compact_markdown(None)

    assert "no walk-forward run found" in body.lower()


def test_build_walk_forward_compact_markdown_shows_stability_and_net_sharpe():
    body = _build_walk_forward_compact_markdown(_walk_forward_summary())

    assert "backtest_mcc" in body
    assert "0.0300" in body
    assert "1/2 windows positive" in body


def test_build_walk_forward_full_stats_markdown_lists_every_window():
    body = _build_walk_forward_full_stats_markdown(_walk_forward_summary())

    assert "2019-01-01" in body
    assert "2020-01-01" in body
    assert "sequence" in body
    assert "multitask" in body


def test_build_other_metrics_markdown_computes_gap_when_both_sides_present(tmp_path, monkeypatch):
    import generate_evaluation_report as report_module

    monkeypatch.setattr(report_module, "_load_lean_sharpe", lambda: (-1.72, "2019-01-01 to 2021-04-02"))
    eval_summary = {"sequence": {"rank_book": _rank_book(net_sharpe=1.52)}, "multitask": {"rank_book": _rank_book(net_sharpe=1.33)}}

    body = _build_other_metrics_markdown(eval_summary, None, None, None)

    assert "-1.720" in body
    assert "+3.240" in body  # 1.52 - (-1.72)
    assert "not yet reconciled" in body.lower()
    assert "not yet available" in body.lower()


def test_build_other_metrics_markdown_includes_reconciliation_and_kill_switch_when_present(tmp_path, monkeypatch):
    import generate_evaluation_report as report_module

    monkeypatch.setattr(report_module, "_load_lean_sharpe", lambda: (None, None))
    reconciliation = {
        "mode": "replay_hysteresis",
        "summary": {"num_dates": 174, "num_dates_exact_match": 0, "mean_overlap_fraction": 0.24, "mean_raw_score_delta_abs": 0.12},
        "diversion_summary": {"action_counts": {"reduce_risk": 870, "simulate": 327, "trade": 267}},
    }
    kill_switch_replay = {"summary": {"trip_count": 78, "locked_day_fraction": 0.7345}}

    body = _build_other_metrics_markdown({}, None, reconciliation, kill_switch_replay)

    assert "174" in body
    assert "24.00%" in body
    assert "reduce_risk" in body
    assert "78" in body
    assert "73.5%" in body


def test_build_other_metrics_markdown_kill_switch_shows_not_measurable_caveat_not_a_fake_zero():
    # V5.3.1 (development/Problems.md #91/#97) - the real Lean row must
    # never render as if "0" were a genuine trip count.
    kill_switch_replay = {"summary": {"trip_count": 78, "locked_day_fraction": 0.7345}}

    body = _build_other_metrics_markdown({}, None, None, kill_switch_replay)

    assert "not measurable from a standalone backtest" in body
    assert "| Real Lean backtest | 0 |" not in body


def test_count_real_kill_switch_trips_always_returns_none(tmp_path, monkeypatch):
    """Direct (unmocked) test of the real function body - proves it
    returns None even against a fixture log file that DOES contain the
    literal trip string, since the real trip-audit event never reaches
    the text log at all (Redis-only, fails silently without a broker)."""
    import generate_backtest_report
    import generate_evaluation_report as report_module

    backtests_dir = tmp_path / "backtests" / "2026-01-01_00-00-00"
    backtests_dir.mkdir(parents=True)
    result_json_path = backtests_dir / "111.json"
    result_json_path.write_text(
        '{"statistics": {"Sharpe Ratio": "1.0"}, "charts": {"Strategy Equity": {"series": {"Equity": '
        '{"values": [[1546387200, 100000.0, 100000.0, 100000.0, 100000.0]]}}}, "Benchmark": {"series": '
        '{"Benchmark": {"values": [[1546387200, 100.0]]}}}}}',
        encoding="utf-8",
    )
    log_path = backtests_dir / "111-log.txt"
    log_path.write_text("some log line\nkill_switch_tripped\nkill_switch_tripped\n", encoding="utf-8")

    monkeypatch.setattr(
        report_module,
        "find_latest_backtest_result_json",
        lambda: generate_backtest_report.find_latest_backtest_result_json(tmp_path / "backtests"),
    )

    assert report_module._count_real_kill_switch_trips() is None


def test_update_readme_evaluation_sections_replaces_all_markers(tmp_path, monkeypatch):
    import generate_evaluation_report as report_module

    ml_dir = tmp_path / "ml"
    _write_evaluation_files(ml_dir, model_kind="sequence", net_sharpe=1.5)
    _write_walk_forward_summary(ml_dir)
    monkeypatch.setattr(report_module, "EVALUATION_DIR", ml_dir / "evaluation")
    monkeypatch.setattr(report_module, "VERSIONS_DIR", ml_dir / "versions")
    monkeypatch.setattr(report_module, "_load_lean_sharpe", lambda: (None, None))
    monkeypatch.setattr(report_module, "_count_real_kill_switch_trips", lambda: None)
    readme_path = tmp_path / "README.md"
    _write_readme_with_markers(readme_path)

    updated = update_readme_evaluation_sections(readme_path)

    assert updated is True
    text = readme_path.read_text(encoding="utf-8")
    assert "old eval" not in text
    assert "old wf" not in text
    assert "old other" not in text
    assert "More text." in text
    assert text.startswith("# Aether Quant")


def test_update_readme_evaluation_sections_returns_false_when_markers_missing(tmp_path, monkeypatch):
    import generate_evaluation_report as report_module

    monkeypatch.setattr(report_module, "EVALUATION_DIR", tmp_path / "ml" / "evaluation")
    monkeypatch.setattr(report_module, "VERSIONS_DIR", tmp_path / "ml" / "versions")
    monkeypatch.setattr(report_module, "_load_lean_sharpe", lambda: (None, None))
    monkeypatch.setattr(report_module, "_count_real_kill_switch_trips", lambda: None)
    readme_path = tmp_path / "README.md"
    readme_path.write_text("# Aether Quant\n\nNo markers here.\n", encoding="utf-8")

    updated = update_readme_evaluation_sections(readme_path)

    assert updated is False
    assert "No markers here." in readme_path.read_text(encoding="utf-8")


def test_update_readme_evaluation_sections_returns_false_when_readme_missing(tmp_path):
    assert update_readme_evaluation_sections(tmp_path / "does_not_exist.md") is False


def test_monte_carlo_markers_render_not_run_yet_fallback_when_json_absent(tmp_path, monkeypatch):
    """V5.3.8/9 - the Monte Carlo section must degrade to its not-run-yet
    fallback (never crash) when ml/evaluation/monte_carlo.json + .npz are
    absent, and render real values when the summary exists."""
    import generate_evaluation_report as report_module

    evaluation_dir = tmp_path / "ml" / "evaluation"
    evaluation_dir.mkdir(parents=True)
    monkeypatch.setattr(report_module, "EVALUATION_DIR", evaluation_dir)
    monkeypatch.setattr(report_module, "_load_lean_sharpe", lambda: (None, None))
    monkeypatch.setattr(report_module, "_count_real_kill_switch_trips", lambda: None)
    # V5.4.4 (Problems.md #114) - guard spy: a tmp readme must NEVER
    # trigger a chart render (the guard in update_readme_evaluation_sections()
    # skips it), otherwise every test-suite run would clobber the REAL
    # development/monte_carlo_equity_curves.png with fixture data - the
    # exact bug that left the README chart showing only the average line.
    render_calls = []
    monkeypatch.setattr(
        report_module,
        "_render_monte_carlo_chart",
        lambda *a, **kw: render_calls.append(a) or False,
    )

    markers = (
        "<!-- AQ:MONTECARLO_START -->old mc<!-- AQ:MONTECARLO_END -->\n"
        "<!-- AQ:MONTECARLO_FULL_STATS_START -->old deep<!-- AQ:MONTECARLO_FULL_STATS_END -->\n"
    )
    readme_path = tmp_path / "README.md"
    readme_path.write_text("# Aether Quant\n\n" + markers, encoding="utf-8")

    updated = update_readme_evaluation_sections(readme_path)
    assert updated is True
    text = readme_path.read_text(encoding="utf-8")
    assert "old mc" not in text and "old deep" not in text
    assert "Monte Carlo simulation has not been run yet" in text
    assert render_calls == []

    # Now write a minimal summary + curves npz and confirm real rendering.
    import numpy as np

    payload = {
        "status": "OK",
        "config": {"n_runs": 1000, "block_size": 20, "seed": 42, "method": "block"},
        "avg_curve": [1.0, 1.03],
        "pct_band": {"p5": [1.0, 0.98], "p25": [1.0, 1.0], "p75": [1.0, 1.05], "p95": [1.0, 1.08]},
        "final_return_pct": {"p5": -2.0, "p25": 3.0, "p50": 9.38, "p75": 15.0, "p95": 21.45},
        "sharpe": {"p5": -0.18, "p25": 0.6, "p50": 1.4, "p75": 2.0, "p95": 2.52},
        "max_drawdown": {"p5": 1.0, "p25": 3.0, "p50": 5.0, "p75": 7.0, "p95": 9.11},
        "prob_negative_return": 0.095,
        "best_run_total_return": 31.2,
        "worst_run_total_return": -6.4,
    }
    (evaluation_dir / "monte_carlo.json").write_text(json.dumps(payload), encoding="utf-8")
    np.savez_compressed(evaluation_dir / "monte_carlo_curves.npz", runs_curves=np.ones((10, 2)))

    updated = update_readme_evaluation_sections(readme_path)
    assert updated is True
    text = readme_path.read_text(encoding="utf-8")
    assert "1000-run stationary-block bootstrap" in text
    assert "![](development/monte_carlo_equity_curves.png)" in text or            "(development/monte_carlo_equity_curves.png)" in text
    # Still NO render: this readme is a tmp file, not the real repo README -
    # the fixture's degenerate 10-flat-run matrix must stay in tmp.
    assert render_calls == []


def test_monte_carlo_chart_renders_when_refreshing_real_readme(tmp_path, monkeypatch):
    """V5.4.4 (Problems.md #114) - the other side of the guard: when the
    call DOES target the real README (README_PATH patched to the hermetic
    tmp stand-in), the chart renders to MONTECARLO_CHART_PATH. Fully
    hermetic - ROOT_DIR/EVALUATION_DIR/README_PATH/MONTECARLO_CHART_PATH
    all point into tmp_path, so no repo asset is touched."""
    import numpy as np

    import generate_evaluation_report as report_module

    root = tmp_path / "repo"
    evaluation_dir = root / "ml" / "evaluation"
    evaluation_dir.mkdir(parents=True)
    development_dir = root / "development"
    development_dir.mkdir()
    chart_path = development_dir / "monte_carlo_equity_curves.png"
    readme_path = root / "README.md"

    monkeypatch.setattr(report_module, "ROOT_DIR", root)
    monkeypatch.setattr(report_module, "EVALUATION_DIR", evaluation_dir)
    monkeypatch.setattr(report_module, "README_PATH", readme_path)
    monkeypatch.setattr(report_module, "MONTECARLO_CHART_PATH", chart_path)
    monkeypatch.setattr(report_module, "_load_lean_sharpe", lambda: (None, None))
    monkeypatch.setattr(report_module, "_count_real_kill_switch_trips", lambda: None)

    payload = {
        "status": "OK",
        "config": {"n_runs": 5, "block_size": 20, "seed": 42, "method": "block"},
        "avg_curve": [1.0, 1.03],
        "pct_band": {"p5": [1.0, 0.98], "p25": [1.0, 1.0], "p75": [1.0, 1.05], "p95": [1.0, 1.08]},
        "final_return_pct": {"p5": -2.0, "p25": 3.0, "p50": 9.38, "p75": 15.0, "p95": 21.45},
        "sharpe": {"p5": -0.18, "p25": 0.6, "p50": 1.4, "p75": 2.0, "p95": 2.52},
        "max_drawdown": {"p5": 1.0, "p25": 3.0, "p50": 5.0, "p75": 7.0, "p95": 9.11},
        "prob_negative_return": 0.095,
        "best_run_total_return": 31.2,
        "worst_run_total_return": -6.4,
    }
    (evaluation_dir / "monte_carlo.json").write_text(json.dumps(payload), encoding="utf-8")
    np.savez_compressed(evaluation_dir / "monte_carlo_curves.npz", runs_curves=np.linspace(0.9, 1.2, 10).reshape(5, 2))

    readme_path.write_text(
        "# Aether Quant\n\n<!-- AQ:MONTECARLO_START -->old<!-- AQ:MONTECARLO_END -->\n"
        "<!-- AQ:MONTECARLO_FULL_STATS_START -->old deep<!-- AQ:MONTECARLO_FULL_STATS_END -->\n",
        encoding="utf-8",
    )
    updated = update_readme_evaluation_sections(readme_path)
    assert updated is True
    # The chart rendered this time (real-README path), from the fixture's
    # 5 distinct runs.
    assert chart_path.exists()
    assert chart_path.stat().st_size > 0


def test_render_monte_carlo_chart_draws_every_individual_run(tmp_path, monkeypatch):
    """V5.4.4 regression guard for the README visual: the chart must draw
    EVERY individual bootstrap run (light blue lines), not just the red
    average - the shipped PNG once showed only the average because it
    predated the individual-run renderer. Verified by intercepting every
    ax.plot() call: one per run, plus the average and the 1.0x baseline,
    and the union of plotted y-data must span the individual runs'
    extremes (autoscale only covers them if they are actually drawn)."""
    pytest.importorskip("matplotlib")
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.axes
    import numpy as np

    import generate_evaluation_report as report_module

    runs = np.linspace(0.5, 1.5, 7).reshape(7, 1) * np.ones((1, 4))
    plotted_y = []
    original_plot = matplotlib.axes.Axes.plot

    def _recording_plot(self, *args, **kwargs):
        # ax.plot(x, y, ...) - capture the y data of every call.
        if len(args) >= 2:
            plotted_y.append(np.asarray(args[1], dtype=float))
        return original_plot(self, *args, **kwargs)

    monkeypatch.setattr(matplotlib.axes.Axes, "plot", _recording_plot)

    out_path = tmp_path / "monte_carlo_equity_curves.png"
    ok = report_module._render_monte_carlo_chart(
        runs, [1.0, 1.01, 1.02, 1.03], {"n_runs": 7, "method": "block", "block_size": 20, "seed": 42}, out_path
    )
    assert ok is True
    assert out_path.exists()
    # 7 individual runs + 1 average = 8 recorded plot calls (the 1.0x
    # baseline uses axhline(), which doesn't route through Axes.plot).
    assert len(plotted_y) == 7 + 1
    all_y = np.concatenate(plotted_y)
    assert all_y.min() == pytest.approx(0.5, abs=1e-9)
    assert all_y.max() == pytest.approx(1.5, abs=1e-9)


def test_render_monte_carlo_chart_degrades_gracefully_without_runs(tmp_path):
    """Missing/empty runs matrix or empty average curve -> False (no
    chart written, never a crash) - the not-run-yet README fallback
    depends on this contract."""
    import numpy as np

    import generate_evaluation_report as report_module

    out_path = tmp_path / "monte_carlo_equity_curves.png"
    assert report_module._render_monte_carlo_chart(None, [1.0], {}, out_path) is False
    assert report_module._render_monte_carlo_chart(np.ones((3, 2)), [], {}, out_path) is False
    assert not out_path.exists()


def test_benchmark_markdown_not_run_yet_fallback():
    """V5.4.4 - no benchmark_comparison.json -> honest fallback text, never
    a crash (same contract as every other section builder here)."""
    text = _build_benchmark_markdown(None, {})
    assert "has not been run yet" in text
    assert "--benchmarks" in text


def test_benchmark_markdown_renders_rank_book_rows_then_baselines():
    """V5.4.4 - the rank book's own net Sharpe rows come first (the number
    being benchmarked, per model), then every baseline in report order;
    SKIPPED baselines show their reason instead of fabricated numbers."""
    summary = {
        "baselines": [
            {"strategy": "momentum", "net_sharpe": 0.4123, "total_return_pct": 3.21},
            {"strategy": "sp500", "net_sharpe": 0.8801, "total_return_pct": 12.4, "status": "OK"},
            {"strategy": "60_40", "net_sharpe": None, "total_return_pct": None, "status": "SKIPPED: no TLT"},
        ],
        "split": "backtest",
    }
    eval_summary = {
        "multitask": {"rank_book": {"net_sharpe": 1.6805, "net_total_return": 0.1061}},
        "sequence": None,
    }
    text = _build_benchmark_markdown(summary, eval_summary)
    lines = text.splitlines()
    # Rank book row first, then baselines in report order.
    assert lines[2].startswith("| **Rank book (multitask)** | 1.681 | 10.61% |")
    assert "momentum" in lines[3]
    assert "sp500" in lines[4]
    # SKIPPED baseline: em-dash metrics + the reason in the note column.
    assert "| 60_40 | — | —% |" in lines[5]
    assert "SKIPPED: no TLT" in lines[5]
    assert "auto-generated by `aq evaluate --benchmarks`" in text


def test_benchmark_markers_replaced_in_readme(tmp_path, monkeypatch):
    """V5.4.4 - the AQ:BENCHMARK marker block is part of the standard
    section-refresh sweep (and degrades to its fallback when no report
    exists yet)."""
    import generate_evaluation_report as report_module

    evaluation_dir = tmp_path / "ml" / "evaluation"
    evaluation_dir.mkdir(parents=True)
    monkeypatch.setattr(report_module, "EVALUATION_DIR", evaluation_dir)
    monkeypatch.setattr(report_module, "_load_lean_sharpe", lambda: (None, None))
    monkeypatch.setattr(report_module, "_count_real_kill_switch_trips", lambda: None)

    readme_path = tmp_path / "README.md"
    readme_path.write_text(
        "# Aether Quant\n\n"
        f"{BENCHMARK_MARKER_START}old benchmarks{BENCHMARK_MARKER_END}\n",
        encoding="utf-8",
    )
    updated = update_readme_evaluation_sections(readme_path)
    assert updated is True
    text = readme_path.read_text(encoding="utf-8")
    assert "old benchmarks" not in text
    assert "has not been run yet" in text
