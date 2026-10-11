"""Forex sleeve research (V5.7.0, plan F4.1 / F4.2 / F4.5): does a concentrated forex book earn its way past IB's $2 minimum?

Forex is switched off because at ~2% of NAV per leg the $2 minimum commission is ~8-10 bps per fill and the gross edge was
~0. This asks the same question for a SLEEVE: its own pool (the forex pairs ranked among themselves), `k` longs and `k`
shorts, a gross budget that makes each leg big enough for the minimum to be small, a 20-bar hold and a dollar deadband.

Everything runs through the same `simulate_rank_book` the as-live book uses (selection, hysteresis, entry lag, per-order
dollar-floor commission) on the forex rows only, on BOTH splits; the rule R-FX (offline half) is applied to the result:

    ships to a Lean backtest only if the sleeve's net Sharpe is > 0 on validation AND on the backtest split AND the forex
    rank IC (within the pairs) is > 0 on validation, and adding it does not lower the main book's backtest Sharpe by > 0.05.

    python scripts/forex_sleeve_research.py [--no-cache]   -> ml/evaluation/forex_sleeve_research.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from as_live_levers import AsLiveHarness  # noqa: E402

from evaluation import simulate_rank_book  # noqa: E402
from evaluation.rank_ic_core import newey_west_t_stat, rank_ic_from_arrays  # noqa: E402
from portfolio.forex_sleeve import build_forex_sleeve_weights  # noqa: E402

NAV = 100_000.0


def forex_rank_ic(frame, score_column: str = "live_rank_score") -> dict:
    """Daily rank IC of the score against the 20d forward return ranked AMONG THE PAIRS (the dataset's own rank target is
    ranked in the full universe, which is the wrong cross-section for a sleeve that only ranks forex)."""
    work = frame.dropna(subset=[score_column, "target_return_20d"]).copy()
    work["own_rank"] = work.groupby("date")["target_return_20d"].rank(pct=True)
    result = rank_ic_from_arrays(
        work[score_column].to_numpy(), work["own_rank"].to_numpy(), work["date"].to_numpy(), min_names_per_date=8
    )
    return {
        "daily_mean_ic": result["mean_ic"], "hac_t": newey_west_t_stat(result["ic_values"], 19), "num_dates": result["num_dates"],
    }


def sleeve_run(frame, base: dict, *, per_side: int, gross: float, rebalance: int, min_trade_usd: float, fee_bps: float, min_usd: float):
    tickers = sorted(frame["ticker"].unique())
    max_weight = gross / (2 * per_side)

    def deadband(*, base_weight, held_weight, **_unused):
        # a resize or entry smaller than the minimum trade is not worth a $2 minimum commission
        if held_weight != 0.0 and abs(base_weight - held_weight) * NAV < min_trade_usd:
            return held_weight
        return base_weight

    kwargs = dict(
        base, prediction_column="live_rank_score", top_n=per_side, bottom_n=per_side, rebalance_every_bars=rebalance,
        gross_exposure=gross, max_weight_per_name=max_weight, max_position_weight=max_weight, min_universe_size=8,
        # the very function main.py's _update_forex_sleeve() calls, so the two cannot disagree on the weights
        raw_weights_fn=lambda allocations, date: build_forex_sleeve_weights(allocations, gross),
        normalize_to_percentile=True, live_weighting=False, sector_by_ticker={}, sector_neutral=False, dollar_neutral=True,
        entry_lag_bars=1, cost_bps_per_side=1.0, commission_bps=fee_bps,
        commission_bps_by_ticker={ticker: fee_bps for ticker in tickers},
        min_commission_usd_by_ticker={ticker: min_usd for ticker in tickers},
        assumed_portfolio_value_usd=NAV, member_weight_fn=deadband,
    )
    return simulate_rank_book(frame, **kwargs)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--no-cache", action="store_true")
    args = parser.parse_args()

    results: dict = {}
    for split in ("validation", "backtest"):
        harness = AsLiveHarness(split, use_cache=not args.no_cache)
        forex = {t for t, kind in harness.asset_class_by_ticker.items() if kind == "forex"}
        frame = harness.lagged_frame[harness.lagged_frame["ticker"].isin(forex)].reset_index(drop=True)
        results[split] = {"forex_rank_ic": forex_rank_ic(frame), "pairs": len(forex), "sleeves": {}}
        print(f"[{split}] forex IC: {results[split]['forex_rank_ic']}")
        for per_side in (2, 3):
            for gross in (0.2, 0.3, 0.4):
                for min_trade_usd in (1000.0, 2500.0):
                    name = f"k={per_side} gross={gross} deadband=${min_trade_usd:.0f}"
                    run = sleeve_run(
                        frame, harness.base, per_side=per_side, gross=gross, rebalance=20,
                        min_trade_usd=min_trade_usd, fee_bps=0.2, min_usd=2.0,
                    )
                    results[split]["sleeves"][name] = {
                        "net_sharpe": run.net_sharpe, "net_return": run.net_total_return, "max_dd": run.net_max_drawdown,
                        "cost_drag_bps": run.cost_drag_annual_bps, "turnover": run.annualized_turnover,
                        "gross_return": run.gross_total_return,
                    }
                    print(
                        f"[{split}] {name:36s} net sharpe {run.net_sharpe:+.3f} ret {100 * run.net_total_return:+.2f}% "
                        f"gross ret {100 * run.gross_total_return:+.2f}% cost {run.cost_drag_annual_bps:.0f}bps/yr"
                    )
    qualifying = [
        name
        for name in results["validation"]["sleeves"]
        if results["validation"]["sleeves"][name]["net_sharpe"] > 0.0
        and results["backtest"]["sleeves"][name]["net_sharpe"] > 0.0
        and results["validation"]["forex_rank_ic"]["daily_mean_ic"] > 0.0
    ]
    results["r_fx_offline_candidates"] = sorted(
        qualifying, key=lambda name: -results["validation"]["sleeves"][name]["net_sharpe"]
    )
    print("R-FX offline candidates (best validation Sharpe first):", results["r_fx_offline_candidates"] or "none")
    out = ROOT_DIR / "ml" / "evaluation" / "forex_sleeve_research.json"
    out.write_text(json.dumps(results, indent=2, default=float), encoding="utf-8")
    print(f"written {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
