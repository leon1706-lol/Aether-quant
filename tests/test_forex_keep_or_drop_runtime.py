"""scripts/forex_keep_or_drop.py's runtime (V6.6.6, #359): R-FX6's decision, the variant keys, and the whole command over the 48-variant grid on three row sets, with the
as-live harness and the simulator stood in (the signal and IC code is the real one from class_sleeve_research)."""

from __future__ import annotations

import json
import sys
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from script_loader import SCRIPTS, load_script

sys.path.insert(0, str(SCRIPTS))

DATES = [day.strftime("%Y-%m-%d") for day in pd.bdate_range("2021-01-04", periods=60)]
TICKERS = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "NZDUSD"]


@pytest.fixture
def module():
    return load_script("forex_keep_or_drop")


def _entry(validation, backtest, span):
    return {"validation": {"net_sharpe": validation}, "backtest": {"net_sharpe": backtest}, "span": {"net_return": span}}


def test_the_sleeve_is_kept_only_when_the_best_validation_variant_is_positive_everywhere(module):
    keep = module.decide({"a": _entry(0.5, 0.2, 0.03), "b": _entry(0.1, 0.9, 0.9)})
    assert keep["branch"] == "keep" and keep["variant"] == "a"
    drop = module.decide({"a": _entry(0.5, -0.1, 0.03), "b": _entry(0.1, 0.9, 0.9)})
    assert drop["branch"] == "drop" and drop["best_validation_variant"] == "a" and drop["checks"]["backtest_sharpe_positive"] is False and "forex_risk.enabled=false" in drop["action"]


def test_a_variant_name_is_the_sleeve_keys_it_stands_for(module):
    assert module.parse_variant("carry_momentum k=2 gross=0.1 reb=20 deadband=$1000") == {"signal": "carry_momentum", "per_side": 2, "gross_budget": 0.1, "rebalance_every_bars": 20, "min_trade_usd": 1000.0}


class Harness:
    def __init__(self, splits, dataset_path):
        rng = np.random.default_rng(6)
        self.asset_class_by_ticker = {ticker: "forex" for ticker in TICKERS} | {"SPY": "equity"}
        rows = [{"date": date, "ticker": ticker, "close": 1.0 + 0.01 * index + rng.normal(0, 0.002), "live_rank_score": rng.random(), "fx_carry_3m": 0.01 * (index - 2) + rng.normal(0, 0.001),
                 "target_return_20d": rng.normal(0, 0.01)} for date in DATES for index, ticker in enumerate(TICKERS + ["SPY"])]
        self.frame = pd.DataFrame(rows)
        self.base = {}
        self.splits = splits


def _stub(monkeypatch, *, keep):
    import importlib

    # the script imports these by name when it runs, so patch the modules as they stand in sys.modules now (another test may have replaced them since collection)
    as_live = importlib.import_module("as_live_levers")
    sleeve = importlib.import_module("class_sleeve_research")
    monkeypatch.setattr(as_live, "AsLiveHarness", Harness)

    def run(frame, base, column, per_side, gross, min_trade_usd, fee_bps, min_usd, rebalance):
        direction = 1.0 if keep else -1.0
        return SimpleNamespace(net_sharpe=direction * (0.2 + gross + per_side * 0.01), net_total_return=direction * 0.05, net_max_drawdown=-0.02, cost_drag_annual_bps=10.0)

    monkeypatch.setattr(sleeve, "sleeve_run", run)


@pytest.mark.parametrize("keep,branch", [(True, "keep"), (False, "drop")])
def test_the_command_scores_every_variant_on_three_row_sets_and_decides(module, monkeypatch, tmp_path, capsys, keep, branch):
    _stub(monkeypatch, keep=keep)
    out = tmp_path / "out" / "forex.json"
    monkeypatch.setattr(sys, "argv", ["forex_keep_or_drop", "--out", str(out), "--dataset", "d.csv"])
    assert module.main() == 0
    written = json.loads(out.read_text(encoding="utf-8"))
    assert written["decision"]["branch"] == branch and len(written["grid"]) == 48 and set(written["ic"]) == {"validation", "backtest", "span"}
    assert ("keys" in written["decision"]) == keep and "R-FX6:" in capsys.readouterr().out
