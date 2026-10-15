"""scripts/forex_keep_or_drop.py (V6.0.0, rule R-FX6): the decision and the variant parser."""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("forex_keep_or_drop", ROOT / "scripts" / "forex_keep_or_drop.py")
research = importlib.util.module_from_spec(spec)
spec.loader.exec_module(research)


def _entry(validation, backtest, span):
    return {"validation": {"net_sharpe": validation}, "backtest": {"net_sharpe": backtest}, "span": {"net_return": span}}


def test_keep_needs_the_best_validation_variant_positive_everywhere():
    grid = {"a": _entry(0.40, 0.10, 0.02), "b": _entry(0.90, -0.10, 0.05), "c": _entry(0.30, 0.50, 0.04)}
    decision = research.decide(grid)
    assert decision["branch"] == "drop" and decision["best_validation_variant"] == "b"  # the pick is by validation only
    assert not decision["checks"]["backtest_sharpe_positive"]
    grid["b"] = _entry(0.90, 0.20, 0.05)
    assert research.decide(grid) == {"branch": "keep", "variant": "b", "checks": {
        "validation_sharpe_positive": True, "backtest_sharpe_positive": True, "span_net_return_positive": True}}


def test_a_negative_span_return_drops_the_sleeve_even_with_positive_sharpes():
    assert research.decide({"a": _entry(0.5, 0.5, -0.001)})["branch"] == "drop"


def test_variant_names_parse_back_into_sleeve_keys():
    assert research.parse_variant("carry_momentum k=2 gross=0.2 reb=40 deadband=$2500") == {
        "signal": "carry_momentum", "per_side": 2, "gross_budget": 0.2, "rebalance_every_bars": 40, "min_trade_usd": 2500.0}
