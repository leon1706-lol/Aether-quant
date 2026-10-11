"""Does the legacy probability-signal sleeve earn anything beyond market exposure? (V5.7.0, todo.md finding 5 / D2.8)

Takes one finished Lean run, picks the non-book equity round trips (`evaluation.backtest_audit` bucketing), and regresses
each trade's return on the market's return over the same holding period (SPY from the dataset closes):

    trade_return = alpha + beta * market_return   (direction-signed, per trade)

A sleeve whose alpha is not distinguishable from zero (|t| < 1) is market beta in a rising market, not skill. Decision
rule (plan D2.8): alpha <= 0 or t < 1 -> halve `phase_v2.legacy_sleeve.max_gross_exposure`; else keep.

    python scripts/sleeve_alpha_check.py [--backtest-dir backtests/<run>] [--market SPY]
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))

from evaluation.backtest_audit import (  # noqa: E402
    _bucketed_trades,
    _parse_time,
    load_backtest_run,
    load_book_history,
    select_run_book_history,
)


def trade_returns(run: dict, book_history: list[dict], bucket: str = "non_member", asset_class: str = "equity") -> list[dict]:
    orders = run["result"].get("orders", {})
    closed = run["result"].get("totalPerformance", {}).get("closedTrades", [])
    rows = []
    for trade_asset_class, trade_bucket, trade in _bucketed_trades(closed, orders, book_history):
        if trade_asset_class != asset_class or trade_bucket != bucket:
            continue
        entry, exit_time = _parse_time(trade.get("entryTime")), _parse_time(trade.get("exitTime"))
        entry_price, quantity = float(trade.get("entryPrice") or 0.0), float(trade.get("quantity") or 0.0)
        if entry is None or exit_time is None or entry_price <= 0.0 or quantity == 0.0:
            continue
        direction = 1.0 if str(trade.get("direction")) in ("0", "long", "Long") else -1.0
        rows.append(
            {
                "symbol": str((trade.get("symbols") or [{}])[0].get("value", "")),
                "entry": entry.date().isoformat(), "exit": exit_time.date().isoformat(), "direction": direction,
                "return": float(trade.get("profitLoss", 0.0) or 0.0) / (entry_price * abs(quantity)),
            }
        )
    return rows


def alpha_beta(rows: list[dict], market_closes: pd.Series) -> dict:
    """OLS of direction-signed trade return on the market return over the same dates (market direction-signed too, so
    a short that loses when the market rises has a negative beta contribution)."""
    xs, ys = [], []
    for row in rows:
        try:
            start = market_closes.loc[:row["entry"]].iloc[-1]
            end = market_closes.loc[:row["exit"]].iloc[-1]
        except IndexError:
            continue
        xs.append(row["direction"] * (end / start - 1.0))
        ys.append(row["return"])
    n = len(xs)
    if n < 5:
        return {"n": n, "alpha": None, "beta": None, "alpha_t": None}
    x, y = np.asarray(xs), np.asarray(ys)
    beta = float(np.cov(x, y, ddof=1)[0, 1] / np.var(x, ddof=1)) if np.var(x, ddof=1) > 0 else 0.0
    alpha = float(y.mean() - beta * x.mean())
    residual = y - alpha - beta * x
    se = math.sqrt(float(residual @ residual) / max(n - 2, 1) / n)
    return {
        "n": n, "alpha": alpha, "beta": beta, "alpha_t": alpha / se if se > 0 else None,
        "mean_trade_return": float(y.mean()), "mean_market_leg": float(x.mean()),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--backtest-dir", default=None)
    parser.add_argument("--market", default="SPY")
    parser.add_argument("--book-run-index", type=int, default=-1)
    args = parser.parse_args()
    run_dir = Path(args.backtest_dir) if args.backtest_dir else sorted(p for p in (ROOT_DIR / "backtests").glob("*") if p.is_dir())[-1]
    run = load_backtest_run(run_dir)
    book_history = select_run_book_history(load_book_history(ROOT_DIR / "visualization" / "book_history.jsonl"), args.book_run_index)
    frame = pd.read_csv(ROOT_DIR / "ml" / "datasets" / "full_dataset.csv", usecols=["date", "ticker", "close"])
    market = frame[frame["ticker"] == args.market].drop_duplicates("date").set_index("date")["close"].sort_index()
    report = {}
    for bucket in ("non_member", "book_member"):
        rows = trade_returns(run, book_history, bucket=bucket)
        report[bucket] = alpha_beta(rows, market)
        print(bucket, json.dumps(report[bucket]))
    sleeve = report["non_member"]
    keep = sleeve["alpha"] is not None and sleeve["alpha"] > 0 and (sleeve["alpha_t"] or 0.0) >= 1.0
    print("legacy sleeve verdict:", "keep (alpha > 0, t >= 1)" if keep else "halve the gross cap (alpha not distinguishable from zero)")
    out = ROOT_DIR / "ml" / "evaluation" / "sleeve_alpha_check.json"
    out.write_text(json.dumps({"run": run_dir.name, "report": report, "keep_sleeve": bool(keep)}, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
