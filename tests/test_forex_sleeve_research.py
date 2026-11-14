"""scripts/forex_sleeve_research.py (V6.6.6): the forex-only rank IC, the sleeve run's settings, and the R-FX candidate list."""

from __future__ import annotations

import json
from types import SimpleNamespace

import numpy as np
import pandas as pd

from script_loader import load_script


def _frame(dates=30, pairs=10, seed=0):
    rng = np.random.default_rng(seed)
    rows = []
    for day in pd.bdate_range("2024-01-01", periods=dates).strftime("%Y-%m-%d"):
        for pair in range(pairs):
            score = rng.normal()
            rows.append({"date": day, "ticker": f"FX{pair}", "live_rank_score": score, "target_return_20d": 0.5 * score + rng.normal()})
    return pd.DataFrame(rows)


def test_the_ic_is_ranked_among_the_pairs_only():
    module = load_script("forex_sleeve_research")
    result = module.forex_rank_ic(_frame())
    assert result["num_dates"] == 30 and result["daily_mean_ic"] > 0.0 and result["hac_t"] is not None


def test_the_sleeve_run_uses_main_pys_weights_and_a_minimum_trade(monkeypatch):
    module = load_script("forex_sleeve_research")
    seen = {}
    monkeypatch.setattr(module, "simulate_rank_book", lambda frame, **kwargs: seen.update(kwargs) or "run")
    monkeypatch.setattr(module, "build_forex_sleeve_weights", lambda allocations, gross: {"gross": gross})
    assert module.sleeve_run(_frame(2), {"base": 1}, per_side=2, gross=0.4, rebalance=20, min_trade_usd=1000.0, fee_bps=0.2, min_usd=2.0) == "run"
    assert seen["base"] == 1 and seen["max_weight_per_name"] == 0.1 and seen["min_commission_usd_by_ticker"]["FX0"] == 2.0
    assert seen["raw_weights_fn"]({}, "d") == {"gross": 0.4}
    deadband = seen["member_weight_fn"]
    assert deadband(base_weight=0.105, held_weight=0.1) == 0.1  # $500 is under the $1,000 minimum
    assert deadband(base_weight=0.2, held_weight=0.1) == 0.2 and deadband(base_weight=0.001, held_weight=0.0) == 0.001


def test_main_lists_sleeves_positive_in_both_splits(tmp_path, monkeypatch, capsys):
    module = load_script("forex_sleeve_research")
    monkeypatch.setattr(module, "ROOT_DIR", tmp_path)
    (tmp_path / "ml" / "evaluation").mkdir(parents=True)

    class Harness:
        def __init__(self, split, use_cache):
            self.asset_class_by_ticker = {"FX0": "forex", "SPY": "equity"}
            self.lagged_frame = pd.DataFrame({"ticker": ["FX0", "SPY"]})
            self.base = {}

    monkeypatch.setattr(module, "AsLiveHarness", Harness)
    monkeypatch.setattr(module, "forex_rank_ic", lambda frame: {"daily_mean_ic": 0.02, "hac_t": 1.0, "num_dates": 5})

    def sleeve_run(frame, base, *, per_side, gross, **kwargs):
        sharpe = 0.5 if (per_side, gross) == (2, 0.2) else 0.3 if (per_side, gross) == (3, 0.4) else -0.1
        return SimpleNamespace(net_sharpe=sharpe, net_total_return=0.01, net_max_drawdown=0.02, cost_drag_annual_bps=5.0, annualized_turnover=2.0, gross_total_return=0.02)

    monkeypatch.setattr(module, "sleeve_run", sleeve_run)
    monkeypatch.setattr(module.sys, "argv", ["x", "--no-cache"])
    assert module.main() == 0
    results = json.loads((tmp_path / "ml" / "evaluation" / "forex_sleeve_research.json").read_text(encoding="utf-8"))
    assert results["r_fx_offline_candidates"][:2] == ["k=2 gross=0.2 deadband=$1000", "k=2 gross=0.2 deadband=$2500"]
    assert len(results["r_fx_offline_candidates"]) == 4 and results["validation"]["pairs"] == 1 and "written" in capsys.readouterr().out
