"""scripts/class_sleeve_research.py's runtime (V6.6.6, #359): the signal columns, the class rank IC, a sleeve run through the real rank-book simulator, the R-SLEEVE
decision and the whole command for both classes, with the as-live harness stood in by a synthetic class frame."""

from __future__ import annotations

import json
import sys
import types
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from script_loader import load_script

DATES = [day.strftime("%Y-%m-%d") for day in pd.bdate_range("2021-01-04", periods=90)]
TICKERS = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "NZDUSD"]


@pytest.fixture
def module(monkeypatch, tmp_path):
    research = load_script("class_sleeve_research")
    (tmp_path / "ml" / "evaluation").mkdir(parents=True)
    monkeypatch.setattr(research, "ROOT_DIR", tmp_path)
    return research


def _frame(*, carry=True, tickers=TICKERS):
    rng = np.random.default_rng(5)
    rows = []
    for date in DATES:
        for index, ticker in enumerate(tickers):
            row = {"date": date, "ticker": ticker, "close": 1.0 + 0.01 * index + rng.normal(0, 0.002), "live_rank_score": rng.random(), "target_return_1d": rng.normal(0, 0.003), "target_return_20d": rng.normal(0, 0.01)}
            if carry:
                row["fx_carry_3m"] = 0.01 * (index - 2) + rng.normal(0, 0.001)
            rows.append(row)
    return pd.DataFrame(rows)


def _base():
    return {"prediction_column": "live_rank_score", "forward_return_column": "target_return_1d", "ticker_column": "ticker", "date_column": "date", "top_n": 6, "bottom_n": 6,
            "rebalance_every_bars": 10, "cost_bps_per_side": 5.0, "commission_bps": 1.0, "gross_exposure": 1.0, "dollar_neutral": True, "sector_neutral": True, "sector_by_ticker": {},
            "hysteresis_rank_margin": 0.0, "max_weight_per_name": 0.12, "min_universe_size": 20, "commission_bps_by_ticker": None}


def test_sharpe_needs_two_varying_observations(module):
    assert module.sharpe([0.01]) == 0.0 and module.sharpe([0.01, 0.01]) == 0.0
    assert module.sharpe([0.01, -0.005, 0.02]) > 0.0


def test_two_runs_are_combined_on_the_union_of_their_dates(module):
    main = SimpleNamespace(per_date=["a", "b", "c"], per_date_net_return=[0.01, -0.01, 0.02])
    sleeve = SimpleNamespace(per_date=["b", "c", "d"], per_date_net_return=[0.005, 0.0, 0.01])
    assert module.combined_sharpe(main, sleeve) != 0.0


def test_forex_gets_carry_and_momentum_signals_and_bonds_only_momentum(module):
    frame = module.add_signal_columns(_frame(), "forex")
    assert {"sig_model_rank", "sig_ts_momentum", "sig_carry", "sig_carry_momentum"} <= set(frame.columns)
    bond = module.add_signal_columns(_frame(carry=False), "bond")
    assert "sig_carry" not in bond.columns and "sig_ts_momentum" in bond.columns
    no_carry = module.add_signal_columns(_frame(carry=False), "forex")
    assert (no_carry["sig_carry"] == 0.0).all()
    flat = _frame()
    flat["close"] = 1.0
    flat["fx_carry_3m"] = 0.0
    assert (module.add_signal_columns(flat, "forex")["sig_carry_momentum"].dropna().abs() < 1e-12).all()


def test_the_class_rank_ic_is_measured_among_the_class_only(module):
    frame = module.add_signal_columns(_frame(), "forex")
    result = module.class_rank_ic(frame, "sig_carry", 4)
    assert set(result) == {"daily_mean_ic", "hac_t", "num_dates"} and result["num_dates"] > 0


def test_a_sleeve_run_trades_the_class_with_a_dollar_deadband(module):
    frame = module.add_signal_columns(_frame(), "forex")
    run = module.sleeve_run(frame, _base(), "sig_carry", per_side=2, gross=0.2, min_trade_usd=2500.0, fee_bps=0.2, min_usd=2.0)
    assert len(run.per_date) > 0 and run.net_sharpe is not None
    tight = module.sleeve_run(frame, _base(), "sig_model_rank", per_side=2, gross=0.2, min_trade_usd=0.0, fee_bps=0.2, min_usd=2.0, rebalance=5)
    assert len(tight.per_date) > 0


def test_a_variant_positive_on_both_splits_with_a_small_drop_ships_otherwise_the_sleeve_ships_at_the_floor(module):
    grid = {"good": {"validation": {"net_sharpe": 0.5}, "backtest": {"net_sharpe": 0.3}, "combined_backtest_drop": 0.01},
            "better_validation_only": {"validation": {"net_sharpe": 0.9}, "backtest": {"net_sharpe": -0.1}, "combined_backtest_drop": 0.0},
            "costly": {"validation": {"net_sharpe": 0.8}, "backtest": {"net_sharpe": 0.4}, "combined_backtest_drop": 0.3}}
    assert module.decide(grid, 0.1) == {"branch": "edge_pass", "variant": "good", "passing": ["good"]}
    verdict = module.decide({name: entry for name, entry in grid.items() if name != "good"}, 0.1)
    assert verdict["branch"] == "trade_anyway_minimum_cap" and verdict["variant"] == "costly" and verdict["gross_cap"] == 0.1


class _Harness:
    def __init__(self, split, use_cache, dataset_path, kind, calls):
        self.split = split
        self.frame = _frame(carry=kind == "forex")
        self.asset_class_by_ticker = {ticker: kind for ticker in TICKERS}
        self.metadata = {ticker: {"trading_eligible": True} for ticker in TICKERS}
        self.base = _base()
        calls.append((split, use_cache, dataset_path))

    def as_live(self, **kwargs):
        shift = 0.0 if kwargs else 0.05
        returns = list(np.sin(np.arange(60)) * 0.004 + shift / 100)
        return SimpleNamespace(net_sharpe=0.4 + shift, net_total_return=0.1, per_date=DATES[:60], per_date_net_return=returns)


@pytest.mark.parametrize("kind,argv", [("forex", ["--asset-class", "forex", "--signals", "carry", "model_rank", "--no-cache", "--dataset-validation", "v.csv"]), ("bond", ["--asset-class", "bond"])])
def test_the_command_scores_the_grid_on_both_splits_and_writes_a_verdict(module, monkeypatch, tmp_path, capsys, kind, argv):
    import evaluation.readme_research as readme_research

    calls = []
    monkeypatch.setattr(module, "AsLiveHarness", lambda split, use_cache, dataset_path: _Harness(split, use_cache, dataset_path, kind, calls))
    refreshed = []
    monkeypatch.setattr(readme_research, "refresh_readme_best_effort", lambda: refreshed.append(True))
    monkeypatch.setattr(sys, "argv", ["class_sleeve_research", *argv])
    assert module.main() == 0
    written = json.loads((tmp_path / "ml" / "evaluation" / f"class_sleeve_research_{kind}.json").read_text(encoding="utf-8"))
    assert [call[0] for call in calls] == ["validation", "backtest"] and refreshed == [True] and written["decision"]["branch"] in ("edge_pass", "trade_anyway_minimum_cap")
    assert set(written["splits"]) == {"validation", "backtest"} and len(written["grid"]) == 24 and "R-SLEEVE decision" in capsys.readouterr().out
    assert types is not None
