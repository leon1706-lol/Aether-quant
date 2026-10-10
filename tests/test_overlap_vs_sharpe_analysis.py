"""scripts/overlap_vs_sharpe_analysis.py: ordinal pairing of reconciled book-history runs with Lean Sharpes.

Regression (V5.6.0): runs sharing one sim window used to be collapsed into a single segment, so the
pairing shrank to one point and shifted every later pair.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "overlap_vs_sharpe_analysis.py"
spec = importlib.util.spec_from_file_location("overlap_vs_sharpe_analysis", SCRIPT)
analysis = importlib.util.module_from_spec(spec)
spec.loader.exec_module(analysis)


def _run(start, end, overlaps):
    return {"run_metadata": {"start_date": start, "end_date": end}, "per_date": [{"overlap_fraction": value} for value in overlaps]}


def test_runs_with_the_same_window_stay_separate_segments():
    runs = [_run("2019-01-02", "2021-03-24", [0.2, 0.4]), _run("2019-01-02", "2021-03-24", [0.5]), _run("2019-01-02", "2021-03-24", [0.9])]

    segments = analysis.segment_overlaps(runs)

    assert [round(s[2], 3) for s in segments] == [0.3, 0.5, 0.9]


def test_runs_without_dates_or_overlap_readings_are_skipped():
    runs = [{"run_metadata": {}, "per_date": [{"overlap_fraction": 0.5}]}, _run("2019-01-02", "2019-02-01", [None]), _run("2019-01-02", "2019-02-01", [0.7])]

    assert [s[2] for s in analysis.segment_overlaps(runs)] == [0.7]


def test_pairing_aligns_the_last_n_segments_with_the_last_n_runs():
    segments = [("a", "b", 0.1, 5), ("a", "b", 0.2, 5), ("a", "b", 0.3, 5)]
    sharpes = [("old", -9.0), ("run2", -2.0), ("run3", -1.0)]

    rows = analysis.pair_ordinally(segments, sharpes)

    assert [(r["backtest_dir"], r["mean_overlap"]) for r in rows] == [("old", 0.1), ("run2", 0.2), ("run3", 0.3)]
    rows = analysis.pair_ordinally(segments[1:], sharpes)
    assert [(r["backtest_dir"], r["mean_overlap"]) for r in rows] == [("run2", 0.2), ("run3", 0.3)]


def test_engine_sharpe_is_the_last_statistics_line():
    text = "STATISTICS:: Sharpe Ratio 0.5\nnoise\nSTATISTICS:: Sharpe Ratio -1.05\n"
    assert analysis.parse_engine_sharpe(text) == pytest.approx(-1.05)
    assert analysis.parse_engine_sharpe("no stats") is None


def test_collect_backtest_sharpes_reads_engine_logs_in_chronological_order(tmp_path):
    for name, text in (("2026-02", "STATISTICS:: Sharpe Ratio 0.1"), ("2026-01", "STATISTICS:: Sharpe Ratio -2.0"), ("2026-03", "crashed")):
        (tmp_path / name).mkdir()
        (tmp_path / name / "log.txt").write_text(text, encoding="utf-8")

    assert analysis.collect_backtest_sharpes(str(tmp_path / "2026-*")) == [("2026-01", -2.0), ("2026-02", 0.1)]
