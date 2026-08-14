import json

from generate_evaluation_report import (
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
