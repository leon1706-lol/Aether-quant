import json
import os

from generate_backtest_report import (
    BACKTEST_MARKER_END,
    BACKTEST_MARKER_START,
    find_latest_backtest_result_json,
    generate_equity_chart,
    load_backtest_summary,
    update_readme_backtest_section,
    update_readme_from_latest_backtest,
)


def _write_result_json(path, *, has_equity_data: bool = True, has_statistics: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    strategy_values = (
        [[1417410000, 100000.0, 100000.0, 100000.0, 100000.0], [1417496400, 101000.0, 101000.0, 101000.0, 101000.0]]
        if has_equity_data
        else []
    )
    benchmark_values = (
        [[1417410000, 180.0], [1417496400, 182.0]] if has_equity_data else []
    )
    statistics = (
        {
            "Sharpe Ratio": "-0.765",
            "Net Profit": "-7.955%",
            "Compounding Annual Return": "-2.212%",
            "Drawdown": "12.100%",
            "Total Orders": "15",
            "Win Rate": "0%",
        }
        if has_statistics
        else {}
    )
    data = {
        "statistics": statistics,
        "charts": {
            "Strategy Equity": {"series": {"Equity": {"values": strategy_values}}},
            "Benchmark": {"series": {"Benchmark": {"values": benchmark_values}}},
        },
    }
    path.write_text(json.dumps(data), encoding="utf-8")


def _set_mtime(path, offset_seconds: float) -> None:
    """Deterministically orders folder mtimes regardless of filesystem
    timestamp resolution or how fast the test itself runs - this module
    picks the "latest" backtest by folder mtime, not by name, specifically
    because non-timestamped folder names (e.g. `lean-local-test-N`) can
    otherwise sort ahead of real ones."""
    now = os.stat(path).st_mtime
    os.utime(path, (now + offset_seconds, now + offset_seconds))


def _write_readme_with_markers(path) -> None:
    path.write_text(
        "# Aether Quant\n\nSome intro.\n\n"
        f"{BACKTEST_MARKER_START}\nold content\n{BACKTEST_MARKER_END}\n\n"
        "More text.\n",
        encoding="utf-8",
    )


def test_find_latest_backtest_result_json_picks_newest_folder_by_mtime(tmp_path):
    """Regression guard for the real bug this shipped with: a non-standard
    folder name (`lean-local-test-9`) sorts *ahead* of every real
    YYYY-MM-DD_HH-MM-SS folder lexicographically, so picking "latest" by
    name alone silently returned a stale, unrelated result. Folder mtime,
    not name, must decide "latest"."""
    backtests_dir = tmp_path / "backtests"
    older_dir = backtests_dir / "lean-local-test-9"
    newer_dir = backtests_dir / "2026-01-01_00-00-00"
    _write_result_json(older_dir / "111.json")
    _write_result_json(newer_dir / "222.json")
    _set_mtime(older_dir, offset_seconds=-100)
    _set_mtime(newer_dir, offset_seconds=0)

    result = find_latest_backtest_result_json(backtests_dir)

    assert result.name == "222.json"


def test_find_latest_backtest_result_json_skips_run_without_equity_data(tmp_path):
    backtests_dir = tmp_path / "backtests"
    older_dir = backtests_dir / "2026-01-01_00-00-00"
    newer_dir = backtests_dir / "2026-06-01_00-00-00"
    _write_result_json(older_dir / "111.json", has_equity_data=True)
    _write_result_json(newer_dir / "222.json", has_equity_data=False)
    _set_mtime(older_dir, offset_seconds=-100)
    _set_mtime(newer_dir, offset_seconds=0)

    result = find_latest_backtest_result_json(backtests_dir)

    assert result.name == "111.json"


def test_find_latest_backtest_result_json_skips_run_without_statistics(tmp_path):
    """Regression guard: a run that was killed/interrupted before finishing
    can leave Lean's result JSON with a partially-populated equity curve
    but an empty `statistics` dict - that must not be picked as "latest"
    over an older, fully-completed run."""
    backtests_dir = tmp_path / "backtests"
    older_dir = backtests_dir / "2026-01-01_00-00-00"
    newer_dir = backtests_dir / "2026-06-01_00-00-00"
    _write_result_json(older_dir / "111.json", has_statistics=True)
    _write_result_json(newer_dir / "222.json", has_statistics=False)
    _set_mtime(older_dir, offset_seconds=-100)
    _set_mtime(newer_dir, offset_seconds=0)

    result = find_latest_backtest_result_json(backtests_dir)

    assert result.name == "111.json"


def test_find_latest_backtest_result_json_ignores_summary_files(tmp_path):
    backtests_dir = tmp_path / "backtests"
    run_dir = backtests_dir / "2026-01-01_00-00-00"
    _write_result_json(run_dir / "111.json")
    (run_dir / "111-summary.json").write_text("{}", encoding="utf-8")

    result = find_latest_backtest_result_json(backtests_dir)

    assert result.name == "111.json"


def test_find_latest_backtest_result_json_returns_none_when_missing(tmp_path):
    assert find_latest_backtest_result_json(tmp_path / "does_not_exist") is None


def test_load_backtest_summary_parses_statistics_and_series(tmp_path):
    result_json = tmp_path / "111.json"
    _write_result_json(result_json)

    summary = load_backtest_summary(result_json)

    assert summary["statistics"]["Sharpe Ratio"] == "-0.765"
    assert summary["strategy_series"] == [(1417410000, 100000.0), (1417496400, 101000.0)]
    assert summary["benchmark_series"] == [(1417410000, 180.0), (1417496400, 182.0)]
    assert summary["start_date"].year == 2014
    assert summary["end_date"].year == 2014


def test_generate_equity_chart_creates_a_nonempty_png(tmp_path):
    summary = load_backtest_summary_from_written(tmp_path)
    output_path = tmp_path / "chart.png"

    generate_equity_chart(summary, output_path)

    assert output_path.exists()
    assert output_path.stat().st_size > 0


def load_backtest_summary_from_written(tmp_path):
    result_json = tmp_path / "111.json"
    _write_result_json(result_json)
    return load_backtest_summary(result_json)


def test_update_readme_backtest_section_replaces_between_markers(tmp_path):
    readme_path = tmp_path / "README.md"
    _write_readme_with_markers(readme_path)
    summary = load_backtest_summary_from_written(tmp_path)
    chart_path = tmp_path / "chart.png"

    updated = update_readme_backtest_section(summary, readme_path, chart_path)

    assert updated is True
    text = readme_path.read_text(encoding="utf-8")
    assert "old content" not in text
    assert "Sharpe Ratio" in text
    assert "-0.765" in text
    assert text.startswith("# Aether Quant")
    assert "More text." in text


def test_headline_table_carries_the_curated_statistics(tmp_path):
    """Every other Lean statistic now lives in the Backtest Statistics sections (evaluation/readme_statistics.py)."""
    readme_path = tmp_path / "README.md"
    _write_readme_with_markers(readme_path)
    summary = load_backtest_summary_from_written(tmp_path)

    assert update_readme_backtest_section(summary, readme_path, tmp_path / "chart.png") is True
    block = readme_path.read_text(encoding="utf-8").split(BACKTEST_MARKER_START)[1].split(BACKTEST_MARKER_END)[0]
    for key in ("Sharpe Ratio", "Net Profit", "Compounding Annual Return", "Drawdown", "Total Orders", "Win Rate"):
        assert key in block


def test_resolve_lean_run_dir_prefers_explicit_then_newest(tmp_path):
    from generate_backtest_report import resolve_lean_run_dir

    assert resolve_lean_run_dir(tmp_path / "given", tmp_path) == tmp_path / "given"
    assert resolve_lean_run_dir(None, tmp_path) is None
    _write_result_json(tmp_path / "2026-06-01_00-00-00" / "222.json")
    assert resolve_lean_run_dir(None, tmp_path) == tmp_path / "2026-06-01_00-00-00"


def test_update_readme_backtest_section_returns_false_when_markers_missing(tmp_path):
    readme_path = tmp_path / "README.md"
    readme_path.write_text("# Aether Quant\n\nNo markers here.\n", encoding="utf-8")
    summary = load_backtest_summary_from_written(tmp_path)

    updated = update_readme_backtest_section(summary, readme_path, tmp_path / "chart.png")

    assert updated is False
    assert "No markers here." in readme_path.read_text(encoding="utf-8")


def test_update_readme_backtest_section_returns_false_when_readme_missing(tmp_path):
    summary = load_backtest_summary_from_written(tmp_path)

    updated = update_readme_backtest_section(summary, tmp_path / "does_not_exist.md", tmp_path / "chart.png")

    assert updated is False


def test_update_readme_from_latest_backtest_end_to_end(tmp_path):
    backtests_dir = tmp_path / "backtests"
    _write_result_json(backtests_dir / "2026-06-01_00-00-00" / "222.json")
    readme_path = tmp_path / "README.md"
    _write_readme_with_markers(readme_path)
    chart_path = tmp_path / "development" / "backtest_equity_chart.png"

    updated = update_readme_from_latest_backtest(backtests_dir, readme_path, chart_path)

    assert updated is True
    assert chart_path.exists()
    text = readme_path.read_text(encoding="utf-8")
    assert "Sharpe Ratio" in text
    assert "backtest_equity_chart.png" in text


def test_update_readme_from_latest_backtest_returns_false_when_no_backtests(tmp_path):
    readme_path = tmp_path / "README.md"
    _write_readme_with_markers(readme_path)

    updated = update_readme_from_latest_backtest(tmp_path / "backtests", readme_path, tmp_path / "chart.png")

    assert updated is False


def test_history_table_lists_finished_runs_newest_first_and_skips_unfinished(tmp_path):
    from generate_backtest_report import build_history_markdown

    backtests_dir = tmp_path / "backtests"
    _write_result_json(backtests_dir / "2026-06-01_00-00-00" / "111.json")
    _write_result_json(backtests_dir / "2026-06-02_00-00-00" / "222.json")
    _write_result_json(backtests_dir / "2026-06-03_00-00-00" / "333.json", has_statistics=False)
    for offset, name in enumerate(("2026-06-01_00-00-00", "2026-06-02_00-00-00", "2026-06-03_00-00-00")):
        _set_mtime(backtests_dir / name, offset * 10.0)

    text = build_history_markdown(backtests_dir)

    rows = [line for line in text.splitlines() if line.startswith("| `")]
    assert [row.split("`")[1] for row in rows] == ["2026-06-02_00-00-00", "2026-06-01_00-00-00"]
    assert "-0.765" in rows[0] and "2014-12-01 to 2014-12-02" in rows[0]


def test_history_table_respects_limit_and_handles_no_runs(tmp_path):
    from generate_backtest_report import build_history_markdown

    assert build_history_markdown(tmp_path / "missing") == "_No finished Lean run yet._"
    backtests_dir = tmp_path / "backtests"
    for day in range(1, 5):
        _write_result_json(backtests_dir / f"2026-06-0{day}_00-00-00" / "1.json")
    assert len([line for line in build_history_markdown(backtests_dir, limit=2).splitlines() if line.startswith("| `")]) == 2


def test_end_to_end_update_fills_the_history_markers(tmp_path):
    from generate_backtest_report import HISTORY_MARKER_END, HISTORY_MARKER_START

    backtests_dir = tmp_path / "backtests"
    _write_result_json(backtests_dir / "2026-06-01_00-00-00" / "222.json")
    readme_path = tmp_path / "README.md"
    _write_readme_with_markers(readme_path)
    readme_path.write_text(
        readme_path.read_text(encoding="utf-8") + f"\n{HISTORY_MARKER_START}\nold\n{HISTORY_MARKER_END}\n", encoding="utf-8"
    )

    assert update_readme_from_latest_backtest(backtests_dir, readme_path, tmp_path / "chart.png") is True

    text = readme_path.read_text(encoding="utf-8")
    assert "| `2026-06-01_00-00-00` |" in text and "\nold\n" not in text


def _write_spy_zip(path, rows):
    import zipfile

    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("spy.csv", "\n".join(rows) + "\n")


def test_a_flat_lean_benchmark_is_redrawn_from_the_daily_zip(tmp_path):
    from generate_backtest_report import benchmark_is_flat, with_daily_benchmark_fallback

    # 2014-12-01 and 2014-12-02 New York midnight, as Lean stamps daily chart points
    summary = {
        "strategy_series": [(1417410000, 100000.0), (1417496400, 101000.0)],
        "benchmark_series": [(1417410000, 425.9975), (1417496400, 425.9975)],
    }
    spy_zip = tmp_path / "spy.zip"
    _write_spy_zip(spy_zip, ["20141128 00:00,2000000,2010000,1990000,2005000,1", "20141201 00:00,2000000,2010000,1990000,2010000,1"])
    assert benchmark_is_flat(summary["benchmark_series"])
    rebuilt = with_daily_benchmark_fallback(summary, spy_zip)
    assert rebuilt["benchmark_source"] == "daily_zip"
    assert rebuilt["benchmark_series"] == [(1417410000, 201.0), (1417496400, 201.0)]


def test_a_moving_benchmark_is_left_alone(tmp_path):
    from generate_backtest_report import with_daily_benchmark_fallback

    summary = {"strategy_series": [(1, 1.0), (2, 2.0)], "benchmark_series": [(1, 180.0), (2, 182.0)]}
    assert with_daily_benchmark_fallback(summary, tmp_path / "absent.zip") is summary


def test_render_a_named_run_and_note_the_stale_benchmark(tmp_path, monkeypatch):
    import generate_backtest_report as report

    backtests_dir = tmp_path / "backtests"
    run = backtests_dir / "2026-06-01_00-00-00"
    _write_result_json(run / "222.json")
    data = json.loads((run / "222.json").read_text(encoding="utf-8"))
    data["charts"]["Benchmark"]["series"]["Benchmark"]["values"] = [[1417410000, 425.9975], [1417496400, 425.9975]]
    (run / "222.json").write_text(json.dumps(data), encoding="utf-8")
    _write_result_json(backtests_dir / "2026-07-01_00-00-00" / "333.json")
    readme_path = tmp_path / "README.md"
    _write_readme_with_markers(readme_path)
    spy_zip = tmp_path / "spy.zip"
    _write_spy_zip(spy_zip, ["20141201 00:00,2000000,2010000,1990000,2010000,1"])
    monkeypatch.setattr(report, "DAILY_SPY_ZIP", spy_zip)

    assert update_readme_from_latest_backtest(backtests_dir, readme_path, tmp_path / "chart.png", run) is True
    text = readme_path.read_text(encoding="utf-8")
    assert "benchmark feed was stale" in text
    assert "2014-12-01" in text


def test_leading_zero_benchmark_points_are_dropped_before_rebasing(tmp_path):
    result = tmp_path / "1.json"
    result.write_text(json.dumps({
        "statistics": {"Sharpe Ratio": "1"},
        "charts": {"Strategy Equity": {"series": {"Equity": {"values": [[1, 1, 1, 1, 100.0], [2, 1, 1, 1, 101.0], [3, 1, 1, 1, 102.0]]}}},
                   "Benchmark": {"series": {"Benchmark": {"values": [[1, 0.0], [2, 300.0], [3, 303.0]]}}}},
    }), encoding="utf-8")
    summary = load_backtest_summary(result)
    assert summary["benchmark_series"] == [(2, 300.0), (3, 303.0)]


def test_a_pinned_run_wins_over_the_newest_and_clearing_the_pin_restores_the_newest(tmp_path, monkeypatch):
    import json as _json

    import generate_backtest_report as report

    backtests = tmp_path / "backtests"
    for name, sharpe in (("2026-10-15_run", "1.0"), ("2026-10-16_run", "2.0")):
        run = backtests / name
        run.mkdir(parents=True)
        (run / "123.json").write_text(_json.dumps({
            "charts": {"Strategy Equity": {"series": {"Equity": {"values": [[1, 1, 1, 1, 1]]}}}},
            "statistics": {"Sharpe Ratio": sharpe},
        }), encoding="utf-8")
    import os

    os.utime(backtests / "2026-10-15_run", (1_000_000, 1_000_000))  # explicit order: the 16th is the newer folder
    os.utime(backtests / "2026-10-16_run", (2_000_000, 2_000_000))
    pin = tmp_path / "pin.json"
    monkeypatch.setattr(report, "BACKTESTS_DIR", backtests)
    monkeypatch.setattr(report, "PIN_PATH", pin)
    assert report.find_latest_backtest_result_json(backtests).parent.name == "2026-10-16_run"
    report.set_pinned_run(backtests / "2026-10-15_run")
    assert report.find_latest_backtest_result_json(backtests).parent.name == "2026-10-15_run"
    report.set_pinned_run(None)
    assert report.find_latest_backtest_result_json(backtests).parent.name == "2026-10-16_run"
    pin.write_text(_json.dumps({"run": "no_such_run"}), encoding="utf-8")  # a stale pin falls back to the newest
    assert report.find_latest_backtest_result_json(backtests).parent.name == "2026-10-16_run"


def test_folders_with_equal_mtimes_are_ordered_by_name(tmp_path):
    import os

    import generate_backtest_report as report

    for name in ("2026-10-15_run", "2026-10-16_run"):
        (tmp_path / name).mkdir()
        (tmp_path / name / "1.json").write_text("{}", encoding="utf-8")
        os.utime(tmp_path / name, (5_000_000, 5_000_000))
    assert [path.parent.name for path in report._iter_backtest_result_jsons(tmp_path)] == ["2026-10-16_run", "2026-10-15_run"]
