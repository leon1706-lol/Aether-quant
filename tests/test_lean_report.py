"""Tests for evaluation/lean_report.py and aq_cli._run_lean_report (V6.3.0): the run-folder tools in order, each step
best-effort, the split periods taken from the config, and the README pin only with an explicit run."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import aq_cli
from evaluation.lean_report import LEAN_REPORT_FLAGS, lean_report_steps, split_periods

CONFIG = {"phase1": {"windows": {
    "backtest": {"start": "2023-07-01", "end": "2025-06-30"},
    "holdout": {"start": "2025-07-01", "end": "2026-09-30"},
}}}


def test_split_periods_reads_the_configured_windows():
    assert split_periods(CONFIG) == ["2023-07-01..2025-06-30", "2025-07-01..2026-09-30"]
    assert split_periods({}) == []


def test_each_step_switches_only_its_own_flag_on():
    steps = lean_report_steps(CONFIG)
    assert [label for label, _ in steps] == [label for label, _ in LEAN_REPORT_FLAGS]
    for (_label, flag), (_, overrides) in zip(LEAN_REPORT_FLAGS, steps):
        assert overrides[flag] is True
        assert sum(1 for _label, name in LEAN_REPORT_FLAGS if overrides[name]) == 1
        assert overrides["lean_report"] is False
    audit = dict(steps)["order-level audit"]
    assert audit["period"] == split_periods(CONFIG)
    assert "period" not in dict(steps)["backtest statistics"]


def test_backtest_statistics_come_last():
    assert LEAN_REPORT_FLAGS[-1][1] == "backtest_stats"


def test_run_lean_report_continues_after_a_failing_step(tmp_path):
    args = aq_cli.build_parser().parse_args(["evaluate", "--lean-report"])
    seen = []

    def fake_evaluate(step_args):
        flag = next(name for _label, name in LEAN_REPORT_FLAGS if getattr(step_args, name))
        seen.append((flag, step_args.backtest_dir))
        if flag == "lean_monte_carlo":
            raise RuntimeError("boom")
        return 1 if flag == "attribute_lean" else 0

    with patch("aq_cli.cmd_evaluate", side_effect=fake_evaluate), patch(
        "generate_backtest_report.update_readme_from_latest_backtest"
    ) as pin:
        exit_code = aq_cli._run_lean_report(args, CONFIG, tmp_path, pin=False)
    assert exit_code == 1
    assert [flag for flag, _ in seen] == [name for _label, name in LEAN_REPORT_FLAGS]
    assert all(run == str(tmp_path) for _, run in seen)
    pin.assert_not_called()


def test_run_lean_report_pins_an_explicit_run(tmp_path):
    args = aq_cli.build_parser().parse_args(["evaluate", "--lean-report", "--backtest-dir", str(tmp_path)])
    with patch("aq_cli.cmd_evaluate", return_value=0), patch(
        "generate_backtest_report.update_readme_from_latest_backtest"
    ) as pin:
        assert aq_cli._run_lean_report(args, CONFIG, Path(tmp_path), pin=True) == 0
    assert pin.call_args.kwargs == {"backtest_dir": Path(tmp_path)}
