"""Every package module with a command line answers --help when run as a script (V6.6.6, #359): the `__main__` guard is code too."""

from __future__ import annotations

import runpy
import sys

import pytest

MODULES = (
    "data_pipeline.cftc_cot", "data_pipeline.dividend_backfill", "data_pipeline.edgar_facts", "data_pipeline.factor_file_backfill", "data_pipeline.fred_backfill",
    "data_pipeline.yfinance_backfill", "evaluation.lean_verdict", "execution.paper_readiness_scheduler",
    "generate_backtest_report", "generate_evaluation_report", "train_cross_sectional", "train_gating", "train_multitask", "train_rl_sizing", "train_sequence",
    "train_strategy_selector", "train_topology", "train",
)


@pytest.mark.parametrize("module", MODULES)
def test_the_module_prints_its_usage_when_run_as_a_script(module, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", [module, "--help"])
    monkeypatch.delitem(sys.modules, module, raising=False)
    with pytest.raises(SystemExit) as raised:
        runpy.run_module(module, run_name="__main__")
    assert raised.value.code == 0 and "usage" in capsys.readouterr().out.lower()
