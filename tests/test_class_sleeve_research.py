"""scripts/class_sleeve_research.py (V5.8.0): the R-SLEEVE decision and the combined-book Sharpe."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def research():
    sys.path.insert(0, str(ROOT / "scripts"))
    spec = importlib.util.spec_from_file_location("class_sleeve_research", ROOT / "scripts" / "class_sleeve_research.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["class_sleeve_research"] = module
    spec.loader.exec_module(module)
    yield module
    sys.modules.pop("class_sleeve_research", None)


def _entry(validation, backtest, drop):
    return {"validation": {"net_sharpe": validation}, "backtest": {"net_sharpe": backtest}, "combined_backtest_drop": drop}


def test_edge_pass_needs_both_splits_positive_and_a_small_combined_drop(research):
    grid = {"a": _entry(0.4, 0.2, 0.01), "b": _entry(0.9, 0.5, 0.20), "c": _entry(-0.1, 0.5, 0.0), "d": _entry(0.6, 0.1, 0.05)}
    decision = research.decide(grid, 0.10)
    assert decision["branch"] == "edge_pass" and decision["variant"] == "d" and decision["passing"] == ["a", "d"]


def test_no_edge_trades_anyway_at_the_minimum_cap(research):
    grid = {"a": _entry(-0.3, 0.1, 0.0), "b": _entry(0.2, -0.3, 0.0)}
    decision = research.decide(grid, 0.10)
    assert decision["branch"] == "trade_anyway_minimum_cap" and decision["gross_cap"] == 0.10 and decision["variant"] == "b"


def test_combined_sharpe_adds_returns_on_the_union_of_dates(research):
    main = SimpleNamespace(per_date=["d1", "d2", "d3"], per_date_net_return=[0.01, -0.01, 0.02])
    sleeve = SimpleNamespace(per_date=["d2", "d4"], per_date_net_return=[0.01, 0.005])
    expected = research.sharpe([0.01, 0.0, 0.02, 0.005])
    assert research.combined_sharpe(main, sleeve) == pytest.approx(expected)


def test_rl_decision_requires_the_trainer_verdict_and_both_splits(research):
    sys.path.insert(0, str(ROOT / "scripts"))
    spec = importlib.util.spec_from_file_location("rl_sizing_research", ROOT / "scripts" / "rl_sizing_research.py")
    rl = importlib.util.module_from_spec(spec)
    sys.modules["rl_sizing_research"] = rl
    spec.loader.exec_module(rl)
    gains = {"0.9-1.1": {"validation": 0.02, "backtest": 0.10}, "0.8-1.2": {"validation": 0.09, "backtest": 0.06}}
    assert rl.decide(True, gains)["branch"] == "edge_pass" and rl.decide(True, gains)["range"] == [0.8, 1.2]
    fallback = rl.decide(False, gains)
    assert fallback["branch"] == "trade_anyway_minimum_range" and fallback["shadow_guard"] is True and fallback["range"] == [0.9, 1.1]
    assert rl.decide(True, {"0.9-1.1": {"validation": 0.0, "backtest": 0.5}})["branch"] == "trade_anyway_minimum_range"
    sys.modules.pop("rl_sizing_research", None)
