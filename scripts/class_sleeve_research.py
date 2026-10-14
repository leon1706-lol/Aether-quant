"""Class sleeve research (V5.8.0): forex and bonds, every signal source, both splits, rule R-SLEEVE.

For one asset class this scores a grid of sleeves — the signal that ranks the class among itself (`model_rank` = the
live blended score, or for forex `carry` / `ts_momentum` / `carry_momentum`, for bonds `ts_momentum`), `per_side`,
gross budget and the dollar deadband — with the same `simulate_rank_book` the as-live book uses, on the class rows only,
on validation AND backtest. The main book is run twice per split (the class in its pool vs out of it) and the sleeve's
daily net returns are added to the "class out" book to get the combined total.

R-SLEEVE (V5.8.0 plan), applied by `decide()`:
  * edge pass   - a variant whose net Sharpe is > 0 on BOTH splits and whose addition lowers the combined backtest
                  Sharpe (vs the main book without the class) by <= 0.05 ships at its researched budget (best
                  validation Sharpe among the passing variants);
  * otherwise   - the sleeve still ships (owner decision: the class must trade) at the MINIMUM cap with the sleeve loss
                  guard; the verdict reports which branch fired and the numbers.

    python scripts/class_sleeve_research.py --asset-class forex|bond [--no-cache] [--signals ...]
    -> ml/evaluation/class_sleeve_research_<class>.json

Signals other than `model_rank` use the dataset's own columns (`close`, `fx_carry_3m`) lagged exactly like live (forex is a
late-bar class: decided on the previous bar). Approximation, stated: the sleeve skips the member sizing chain (liquidity
gate, net-edge gate) the live path applies; it charges the per-order dollar minimum and the configured commission.
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
sys.path.insert(0, str(Path(__file__).resolve().parent))

from as_live_levers import AsLiveHarness, add_split_dataset_args, dataset_for_split  # noqa: E402

from evaluation import simulate_rank_book  # noqa: E402
from evaluation.live_parity import lag_predictions_for_tickers  # noqa: E402
from evaluation.rank_ic_core import newey_west_t_stat, rank_ic_from_arrays  # noqa: E402
from features.fx_signals import ts_momentum_series  # noqa: E402
from portfolio.class_sleeve import build_class_sleeve_weights  # noqa: E402

NAV = 100_000.0
MIN_CAP = {"forex": 0.10, "bond": 0.10}
SIGNALS = {"forex": ("model_rank", "carry", "ts_momentum", "carry_momentum"), "bond": ("model_rank", "ts_momentum")}
MAX_COMBINED_BACKTEST_SHARPE_DROP = 0.05


def sharpe(returns: list[float]) -> float:
    values = np.asarray(returns, dtype=float)
    if len(values) < 2 or values.std(ddof=1) == 0.0:
        return 0.0
    return float(values.mean() / values.std(ddof=1) * math.sqrt(252))


def combined_sharpe(main_run, sleeve_run) -> float:
    """Sharpe of main + sleeve daily net returns on the union of their dates (a date missing from one adds 0)."""
    series = pd.Series(main_run.per_date_net_return, index=main_run.per_date, dtype=float).add(
        pd.Series(sleeve_run.per_date_net_return, index=sleeve_run.per_date, dtype=float), fill_value=0.0
    )
    return sharpe(series.tolist())


def add_signal_columns(frame: pd.DataFrame, asset_class: str) -> pd.DataFrame:
    """Per-signal score columns from the dataset's own history (momentum from `close`, carry from `fx_carry_3m`)."""
    frame = frame.sort_values(["ticker", "date"]).copy()
    frame["sig_model_rank"] = frame["live_rank_score"]
    frame["sig_ts_momentum"] = frame.groupby("ticker")["close"].transform(ts_momentum_series)
    if asset_class == "forex":
        carry = frame["fx_carry_3m"] if "fx_carry_3m" in frame.columns else pd.Series(0.0, index=frame.index)
        frame["sig_carry"] = carry.astype(float)
        zscore = lambda column: frame.groupby("date")[column].transform(  # noqa: E731
            lambda values: (values - values.mean()) / values.std(ddof=1) if values.std(ddof=1) > 0 else values * 0.0
        )
        frame["sig_carry_momentum"] = 0.5 * (zscore("sig_carry") + zscore("sig_ts_momentum"))
    return frame


def class_rank_ic(frame: pd.DataFrame, column: str, min_names: int) -> dict:
    """Daily rank IC of `column` against the 20d forward return ranked AMONG the class (the sleeve's cross-section)."""
    work = frame.dropna(subset=[column, "target_return_20d"]).copy()
    work["own_rank"] = work.groupby("date")["target_return_20d"].rank(pct=True)
    result = rank_ic_from_arrays(
        work[column].to_numpy(), work["own_rank"].to_numpy(), work["date"].to_numpy(), min_names_per_date=min_names
    )
    return {"daily_mean_ic": result["mean_ic"], "hac_t": newey_west_t_stat(result["ic_values"], 19), "num_dates": result["num_dates"]}


def sleeve_run(frame, base: dict, signal_column: str, *, per_side: int, gross: float, min_trade_usd: float,
               fee_bps: float, min_usd: float, rebalance: int = 20):
    tickers = sorted(frame["ticker"].unique())
    max_weight = gross / (2 * per_side)

    def deadband(*, base_weight, held_weight, **_unused):
        if held_weight != 0.0 and abs(base_weight - held_weight) * NAV < min_trade_usd:
            return held_weight
        return base_weight

    kwargs = dict(
        base, prediction_column=signal_column, top_n=per_side, bottom_n=per_side, rebalance_every_bars=rebalance,
        gross_exposure=gross, max_weight_per_name=max_weight, max_position_weight=max_weight,
        min_universe_size=max(2 * per_side, 4),
        raw_weights_fn=lambda allocations, date: build_class_sleeve_weights(allocations, gross),
        normalize_to_percentile=True, live_weighting=False, sector_by_ticker={}, sector_neutral=False, dollar_neutral=True,
        entry_lag_bars=1, cost_bps_per_side=1.0, commission_bps=fee_bps,
        commission_bps_by_ticker={ticker: fee_bps for ticker in tickers},
        min_commission_usd_by_ticker={ticker: min_usd for ticker in tickers},
        assumed_portfolio_value_usd=NAV, member_weight_fn=deadband,
    )
    return simulate_rank_book(frame, **kwargs)


def decide(grid: dict, minimum_cap: float) -> dict:
    """R-SLEEVE over `grid` = {variant: {"validation": {...}, "backtest": {...}, "combined_backtest_drop": float}}."""
    passing = [
        name for name, entry in grid.items()
        if entry["validation"]["net_sharpe"] > 0.0 and entry["backtest"]["net_sharpe"] > 0.0
        and entry["combined_backtest_drop"] <= MAX_COMBINED_BACKTEST_SHARPE_DROP
    ]
    if passing:
        best = max(passing, key=lambda name: grid[name]["validation"]["net_sharpe"])
        return {"branch": "edge_pass", "variant": best, "passing": sorted(passing)}
    best_effort = max(grid, key=lambda name: grid[name]["validation"]["net_sharpe"] + grid[name]["backtest"]["net_sharpe"])
    return {"branch": "trade_anyway_minimum_cap", "variant": best_effort, "gross_cap": minimum_cap,
            "reason": "no variant is net-positive on both splits with a combined-book drop <= 0.05"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--asset-class", choices=sorted(SIGNALS), required=True)
    parser.add_argument("--signals", nargs="*", default=None)
    parser.add_argument("--no-cache", action="store_true")
    add_split_dataset_args(parser)
    args = parser.parse_args()
    asset_class = args.asset_class
    signals = args.signals or list(SIGNALS[asset_class])
    fee_bps, min_usd = (0.2, 2.0) if asset_class == "forex" else (1.0, 1.0)
    per_sides, grosses, deadbands = ((2, 3), (0.10, 0.20, 0.30), (1000.0, 2500.0)) if asset_class == "forex" else ((2, 3), (0.10, 0.20, 0.30), (500.0, 1500.0))

    grid: dict = {}
    summary: dict = {"asset_class": asset_class, "splits": {}}
    for split in ("validation", "backtest"):
        harness = AsLiveHarness(split, use_cache=not args.no_cache, dataset_path=dataset_for_split(args, split))
        members = {t for t, kind in harness.asset_class_by_ticker.items() if kind == asset_class}
        late = asset_class in ("forex", "crypto")
        frame = add_signal_columns(harness.frame, asset_class)
        frame = frame[frame["ticker"].isin(members)].reset_index(drop=True)
        for column in [c for c in frame.columns if c.startswith("sig_")]:
            if late:
                frame = lag_predictions_for_tickers(frame, prediction_column=column, tickers=members)
        metadata_out = {t: dict(v, trading_eligible=False) if t in members else v for t, v in harness.metadata.items()}
        main_in = harness.as_live()
        main_out = harness.as_live(candidate_metadata_by_ticker=metadata_out)
        summary["splits"][split] = {
            "members": len(members),
            "main_with_class_in_pool": {"net_sharpe": main_in.net_sharpe, "net_return": main_in.net_total_return},
            "main_without_class": {"net_sharpe": main_out.net_sharpe, "net_return": main_out.net_total_return},
            "class_rank_ic": {s: class_rank_ic(frame, f"sig_{s}", max(4, 2 * 2)) for s in signals},
        }
        print(f"[{split}] main with class {main_in.net_sharpe:+.3f} / without {main_out.net_sharpe:+.3f}")
        for signal in signals:
            print(f"[{split}] {signal} IC {summary['splits'][split]['class_rank_ic'][signal]}")
            for per_side in per_sides:
                for gross in grosses:
                    for min_trade_usd in deadbands:
                        name = f"{signal} k={per_side} gross={gross} deadband=${min_trade_usd:.0f}"
                        run = sleeve_run(frame, harness.base, f"sig_{signal}", per_side=per_side, gross=gross,
                                         min_trade_usd=min_trade_usd, fee_bps=fee_bps, min_usd=min_usd)
                        entry = grid.setdefault(name, {})
                        entry[split] = {"net_sharpe": run.net_sharpe, "net_return": run.net_total_return,
                                        "max_dd": run.net_max_drawdown, "cost_drag_bps": run.cost_drag_annual_bps,
                                        "gross_return": run.gross_total_return}
                        if split == "backtest":
                            entry["combined_backtest_sharpe"] = combined_sharpe(main_out, run)
                            entry["combined_backtest_drop"] = main_out.net_sharpe - entry["combined_backtest_sharpe"]
                        print(f"[{split}] {name:48s} net sharpe {run.net_sharpe:+.3f} ret {100 * run.net_total_return:+.2f}%")
    complete = {name: entry for name, entry in grid.items() if "validation" in entry and "backtest" in entry}
    summary["grid"] = complete
    summary["decision"] = decide(complete, MIN_CAP[asset_class])
    print("R-SLEEVE decision:", json.dumps(summary["decision"]))
    out = ROOT_DIR / "ml" / "evaluation" / f"class_sleeve_research_{asset_class}.json"
    out.write_text(json.dumps(summary, indent=2, default=float), encoding="utf-8")
    print(f"written {out}")

    from evaluation.readme_research import refresh_readme_best_effort

    refresh_readme_best_effort()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
