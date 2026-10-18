"""Predict a Lean run WITH the T-bill cash sweep from a finished run WITHOUT it (V6.2.0, written before BT1).

The sweep stays outside the strategy's risk controls (the kill switch and the drawdown lock read the strategy value
without it), so the book's decisions do not change and the run's own daily holdings and rebalance calendar decide the
sweep exactly as main.py would (portfolio/cash_sweep.py):

  * holdings after day D's orders = the positions at the end of the next equity session (orders fill at its open);
  * a rebalance attempt next session = the next session is a book-history date (live logs every attempt, engaged or
    vetoed); the formed book = the last attempt's target weights (empty after a veto, as live's _book_target_weights);
  * the sweep decided on D is bought at D+1 and earns BIL's close-to-close moves from then on; IB's per-share fee
    ($0.005, $1 minimum) and the configured slippage are charged on every trade.

The counterfactual daily performance (Lean's own list plus the sweep's P&L over the previous day's equity) is priced
with evaluation/lean_statistics.py on the refreshed risk-free file at 252 and 365 days a year.

    python scripts/predict_sweep_bt1.py [--backtest-dir backtests/2026-10-16_18-23-01] [--out ml/evaluation/v620/bt1_prediction.json]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))

IB_FEE_PER_SHARE = 0.005
IB_MIN_FEE = 1.0


def main() -> int:
    from evaluation.backtest_audit import daily_equity_from_chart, load_backtest_run
    from evaluation.lean_attribution import (
        LEAN_EQUITY_PRICE_SCALE,
        closes_for_universe,
        daily_ticker_pnl,
        fills_from_order_events,
        find_book_history_for_run,
        read_daily_closes,
        run_config_path,
    )
    from evaluation.lean_statistics import (
        lean_statistics,
        load_backtest_series,
        load_interest_rate_changes,
        with_extra_daily_returns,
    )
    from json_safety import atomic_write_json, sanitize_json_finite
    from portfolio.cash_sweep import cash_sweep_target_weight, margin_fraction, resolve_cash_sweep_config, strategy_reserve

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--backtest-dir", default=str(ROOT_DIR / "backtests" / "2026-10-16_18-23-01"))
    parser.add_argument("--out", default=str(ROOT_DIR / "ml" / "evaluation" / "v620" / "bt1_prediction.json"))
    args = parser.parse_args()

    run_dir = Path(args.backtest_dir)
    config = json.loads(Path(run_config_path(run_dir, ROOT_DIR)).read_text(encoding="utf-8"))
    shipped = json.loads((ROOT_DIR / "config.json").read_text(encoding="utf-8"))
    sweep_config = dict(resolve_cash_sweep_config(shipped["phase_v2"].get("cash_sweep")), enabled=True)
    history_path = find_book_history_for_run(run_dir, ROOT_DIR / "visualization" / "book_history")
    history = [json.loads(line) for line in history_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    attempts = {record["date"]: {key: float(value.get("target_weight", 0.0)) for key, value in (record.get("allocations") or {}).items()}
                for record in history}

    run = load_backtest_run(run_dir)
    fills = fills_from_order_events(run["order_events"])
    daily_equity = daily_equity_from_chart(run["result"])
    equity_by_date = dict(daily_equity)
    dates = [date for date, _ in daily_equity]
    closes = closes_for_universe(config, ROOT_DIR, {fill.ticker for fill in fills})
    forex = {str(a["ticker"]).upper() for a in config["phase1"]["universe"]["assets"] if a.get("security_type") == "forex"}
    ticker_pnl = daily_ticker_pnl(fills, closes, dates, forex)
    types = {str(a["ticker"]).upper(): str(a.get("security_type", "equity")) for a in config["phase1"]["universe"]["assets"]}
    bil = read_daily_closes(ROOT_DIR / sweep_config["data_path"], LEAN_EQUITY_PRICE_SCALE)
    spy = read_daily_closes(ROOT_DIR / "data" / "equity" / "usa" / "daily" / "spy.zip", LEAN_EQUITY_PRICE_SCALE)
    sessions = [date for date in sorted(spy) if dates[0] <= date <= dates[-1]]

    phase_v2 = config["phase_v2"]
    legacy, bond = phase_v2.get("legacy_sleeve", {}), phase_v2.get("bond_sleeve", {})
    other = float(legacy.get("max_gross_exposure", 0.0)) if legacy.get("enabled") else 0.0
    neutral = float(bond.get("gross_budget", 0.0)) if bond.get("enabled") else 0.0
    cap = float(phase_v2["portfolio_book"]["neutrality"]["gross_exposure_cap"])
    max_short = float(config.get("phase9", {}).get("portfolio", {}).get("max_short_exposure", 0.30))

    positions_by_date: dict[str, dict[str, float]] = {}
    running: dict[str, float] = {}
    for date in sorted(ticker_pnl):
        for ticker, entry in ticker_pnl[date].items():
            running[ticker] = float(entry["position"])
        positions_by_date[date] = dict(running)

    shares, pnl_by_date, weights, cash_floor, trades, fees = 0, {}, [], [], 0, 0.0
    formed: dict[str, float] = {}
    pending_shares = None
    previous_bil = None
    for date in dates:
        price = bil.get(date)
        if price is not None:
            if previous_bil is not None and shares:
                pnl_by_date[date] = pnl_by_date.get(date, 0.0) + shares * (price - previous_bil)
            previous_bil = price
        if pending_shares is not None and date in bil:  # the order placed on the previous session fills today
            traded = abs(pending_shares - shares)
            if traded:
                cost = max(IB_MIN_FEE, IB_FEE_PER_SHARE * traded) + traded * price * sweep_config["cost_bps_per_side"] / 1e4
                pnl_by_date[date] = pnl_by_date.get(date, 0.0) - cost
                fees += cost
                trades += 1
            shares, pending_shares = pending_shares, None
        if date not in spy:
            continue
        if date in attempts:
            formed = attempts[date]
        position = sessions.index(date)
        next_session = sessions[position + 1] if position + 1 < len(sessions) else None
        if next_session is None or date not in bil:
            continue
        equity = equity_by_date.get(next_session) or equity_by_date.get(date)
        holdings = positions_by_date.get(next_session, {})
        long_weight = short_weight = book_long = book_short = 0.0
        margin_inputs = []
        for ticker, quantity in holdings.items():
            close = closes.get(ticker, {}).get(next_session)
            if not quantity or close is None or not equity:
                continue
            weight = quantity * close / equity
            margin_inputs.append((types.get(ticker, "equity"), weight))
            if weight > 0:
                long_weight += weight
                book_long += weight if ticker in formed else 0.0
            else:
                short_weight -= weight
                book_short -= weight if ticker in formed else 0.0
        reserve = strategy_reserve(
            rebalance_next=next_session in attempts, book_gross_cap=cap, max_short_exposure=max_short,
            formed_long=sum(w for w in formed.values() if w > 0), formed_short=-sum(w for w in formed.values() if w < 0),
            book_long=book_long, book_short=book_short, other_budget_remaining=other, neutral_budget=neutral,
        )
        target = cash_sweep_target_weight(long_weight=long_weight, short_weight=short_weight,
                                          margin_used=margin_fraction(margin_inputs), reserve=reserve, config=sweep_config)
        current = shares * price / equity_by_date.get(date, equity)
        weights.append(target)
        cash_floor.append(1.0 - long_weight + short_weight - target)
        if current > target + 1e-9 or abs(target - current) >= sweep_config["min_trade_weight"]:
            pending_shares = int(target * equity_by_date.get(date, equity) / price)

    series = load_backtest_series(next(path for path in run_dir.glob("*.json") if path.stem.isdigit()))
    previous_equity = {date: value for (date, value) in zip(dates[1:], [v for _, v in daily_equity[:-1]])}
    extra = {}
    from datetime import date as _date

    for day in series["performance_dates"]:
        key = day.isoformat()
        if key in pnl_by_date and previous_equity.get(key):
            extra[_date.fromisoformat(key)] = pnl_by_date[key] / previous_equity[key]
    counterfactual = with_extra_daily_returns(series["performance"], series["performance_dates"], extra)
    refreshed = load_interest_rate_changes(ROOT_DIR / "data" / "alternative" / "interest-rate" / "usa" / "interest-rate.csv")
    old_file = ROOT_DIR / "ml" / "evaluation" / "v620" / "interest-rate_pre_v620.csv"
    stats = {}
    for label, changes in (("refreshed", refreshed), ("pre_v620", load_interest_rate_changes(old_file) if old_file.exists() else refreshed)):
        for days in (252, 365):
            stats[f"with_sweep/{label}/{days}"] = lean_statistics(counterfactual, series["equity_dates"], trading_days_per_year=days, rate_changes=changes)
            stats[f"without_sweep/{label}/{days}"] = lean_statistics(series["performance"], series["equity_dates"], trading_days_per_year=days, rate_changes=changes)

    cumulative, peak, drawdown, equity_with = 0.0, 0.0, 0.0, []
    for date, value in daily_equity:
        cumulative += pnl_by_date.get(date, 0.0)
        total = value + cumulative
        peak = max(peak, total)
        drawdown = min(drawdown, total / peak - 1.0)
        equity_with.append(total)
    report = {
        "run": run_dir.name, "book_history": history_path.name, "written_before_bt1": True,
        "sweep_config": sweep_config,
        "sweep_net_pnl_usd": sum(pnl_by_date.values()), "sweep_fees_usd": fees, "sweep_trades": trades,
        "mean_target_weight": sum(weights) / len(weights) if weights else 0.0, "max_target_weight": max(weights or [0.0]),
        "min_cash_fraction_after_sweep": min(cash_floor or [1.0]),
        "end_equity_without": daily_equity[-1][1], "end_equity_with": equity_with[-1] if equity_with else None,
        "max_drawdown_with_sweep": drawdown,
        "lean_statistics": stats,
    }
    atomic_write_json(Path(args.out), sanitize_json_finite(report), indent=2)
    print(f"{run_dir.name} + sweep: P&L ${report['sweep_net_pnl_usd']:,.0f} (fees ${fees:,.0f}, {trades} trades), mean weight "
          f"{report['mean_target_weight']:.2f}, max {report['max_target_weight']:.2f}, min cash {report['min_cash_fraction_after_sweep']:.3f}, "
          f"drawdown {drawdown:.2%}")
    for key in ("without_sweep/pre_v620/252", "without_sweep/refreshed/365", "with_sweep/refreshed/252", "with_sweep/refreshed/365"):
        print(f"  {key:30s} Sharpe {stats[key]['sharpe_ratio']:+.3f}  annual {stats[key]['annual_return']:+.2%}  "
              f"std {stats[key]['annual_standard_deviation']:.4f}")
    print(f"written {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
