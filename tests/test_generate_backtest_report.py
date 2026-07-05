import json
import os

from generate_backtest_report import (
    BACKTEST_MARKER_END,
    BACKTEST_MARKER_START,
    FULL_STATS_MARKER_END,
    FULL_STATS_MARKER_START,
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
        f"{FULL_STATS_MARKER_START}\nold full stats\n{FULL_STATS_MARKER_END}\n\n"
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


def test_update_readme_backtest_section_also_fills_in_full_stats_table(tmp_path):
    """The compact summary table only shows a curated subset of Lean's
    statistics - the full-stats block below it must show every field Lean
    reports, not just the curated highlights."""
    readme_path = tmp_path / "README.md"
    _write_readme_with_markers(readme_path)
    summary = load_backtest_summary_from_written(tmp_path)

    updated = update_readme_backtest_section(summary, readme_path, tmp_path / "chart.png")

    assert updated is True
    text = readme_path.read_text(encoding="utf-8")
    assert "old full stats" not in text
    full_stats_block = text.split(FULL_STATS_MARKER_START)[1].split(FULL_STATS_MARKER_END)[0]
    for key in ("Sharpe Ratio", "Net Profit", "Compounding Annual Return", "Drawdown", "Total Orders", "Win Rate"):
        assert key in full_stats_block


def test_update_readme_backtest_section_tolerates_missing_full_stats_markers(tmp_path):
    """Older READMEs without the full-stats markers must still get the
    compact summary/chart section updated - a missing optional block must
    never block the rest of the update."""
    readme_path = tmp_path / "README.md"
    readme_path.write_text(
        f"# Aether Quant\n\n{BACKTEST_MARKER_START}\nold content\n{BACKTEST_MARKER_END}\n\nMore text.\n",
        encoding="utf-8",
    )
    summary = load_backtest_summary_from_written(tmp_path)

    updated = update_readme_backtest_section(summary, readme_path, tmp_path / "chart.png")

    assert updated is True
    text = readme_path.read_text(encoding="utf-8")
    assert "Sharpe Ratio" in text
    assert "More text." in text


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
