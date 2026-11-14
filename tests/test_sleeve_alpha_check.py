"""scripts/sleeve_alpha_check.py (V6.6.6): each closed trade's return regressed on the market's, and the keep-or-halve verdict."""

from __future__ import annotations

import json

import numpy as np
import pandas as pd

from script_loader import load_script


def _trade(entry, exit_time, *, price=100.0, quantity=10.0, pnl=10.0, direction="0", symbol="AAA"):
    return {"entryTime": entry, "exitTime": exit_time, "entryPrice": price, "quantity": quantity, "profitLoss": pnl, "direction": direction, "symbols": [{"value": symbol}]}


def test_trade_returns_keep_only_the_bucket_and_class_asked_for(monkeypatch):
    module = load_script("sleeve_alpha_check")
    trades = [
        ("equity", "non_member", _trade("2024-01-02T10:00:00", "2024-01-05T10:00:00")),
        ("equity", "non_member", _trade("2024-01-02T10:00:00", "2024-01-05T10:00:00", direction="1", pnl=-5.0)),
        ("equity", "book_member", _trade("2024-01-02T10:00:00", "2024-01-05T10:00:00")),
        ("crypto", "non_member", _trade("2024-01-02T10:00:00", "2024-01-05T10:00:00")),
        ("equity", "non_member", _trade(None, "2024-01-05T10:00:00")),
        ("equity", "non_member", _trade("2024-01-02T10:00:00", "2024-01-05T10:00:00", price=0.0)),
    ]
    monkeypatch.setattr(module, "_bucketed_trades", lambda closed, orders, history: trades)
    rows = module.trade_returns({"result": {}}, [])
    assert [(row["direction"], row["return"]) for row in rows] == [(1.0, 0.01), (-1.0, -0.005)]
    assert rows[0] == {"symbol": "AAA", "entry": "2024-01-02", "exit": "2024-01-05", "direction": 1.0, "return": 0.01}


def test_alpha_beta_needs_five_trades_and_reports_the_fit():
    module = load_script("sleeve_alpha_check")
    market = pd.Series(np.linspace(100.0, 130.0, 31), index=[f"2024-01-{day:02d}" for day in range(1, 32)])
    rows = [{"entry": f"2024-01-{day:02d}", "exit": f"2024-01-{day + 3:02d}", "direction": 1.0, "return": 0.01 + 0.001 * day} for day in range(2, 10)]
    rows.append({"entry": "2023-12-01", "exit": "2024-01-03", "direction": 1.0, "return": 0.0})  # before the market data
    fit = module.alpha_beta(rows, market)
    assert fit["n"] == 8 and fit["alpha_t"] is not None and fit["beta"] != 0.0
    assert module.alpha_beta(rows[:3], market) == {"n": 3, "alpha": None, "beta": None, "alpha_t": None}
    flat = pd.Series(100.0, index=market.index)
    exact = [dict(row, **{"return": 0.02}) for row in rows[:8]]
    flat_fit = module.alpha_beta(exact, flat)
    assert flat_fit["beta"] == 0.0 and flat_fit["alpha_t"] is None


def _tree(root):
    (root / "backtests" / "2024-01-01_run").mkdir(parents=True)
    (root / "ml" / "datasets").mkdir(parents=True)
    (root / "ml" / "evaluation").mkdir(parents=True)
    pd.DataFrame({"date": ["2024-01-02", "2024-01-02", "2024-01-03"], "ticker": ["SPY", "SPY", "SPY"], "close": [1.0, 1.0, 2.0]}).to_csv(root / "ml" / "datasets" / "full_dataset.csv", index=False)


def test_main_writes_the_verdict_for_the_newest_run(tmp_path, monkeypatch, capsys):
    module = load_script("sleeve_alpha_check")
    _tree(tmp_path)
    monkeypatch.setattr(module, "ROOT_DIR", tmp_path)
    monkeypatch.setattr(module, "load_backtest_run", lambda run_dir: {"dir": run_dir})
    monkeypatch.setattr(module, "load_book_history", lambda path: [])
    monkeypatch.setattr(module, "select_run_book_history", lambda history, index: history)
    monkeypatch.setattr(module, "trade_returns", lambda run, history, bucket: [])
    fits = iter([{"alpha": 0.01, "alpha_t": 2.0}, {"alpha": None}, {"alpha": -0.01, "alpha_t": None}, {"alpha": None}])
    monkeypatch.setattr(module, "alpha_beta", lambda rows, market: next(fits))
    monkeypatch.setattr(module.sys, "argv", ["x"])
    assert module.main() == 0
    written = json.loads((tmp_path / "ml" / "evaluation" / "sleeve_alpha_check.json").read_text(encoding="utf-8"))
    assert written["run"] == "2024-01-01_run" and written["keep_sleeve"] is True
    monkeypatch.setattr(module.sys, "argv", ["x", "--backtest-dir", str(tmp_path / "backtests" / "2024-01-01_run")])
    assert module.main() == 0
    assert json.loads((tmp_path / "ml" / "evaluation" / "sleeve_alpha_check.json").read_text(encoding="utf-8"))["keep_sleeve"] is False
    assert "halve the gross cap" in capsys.readouterr().out
