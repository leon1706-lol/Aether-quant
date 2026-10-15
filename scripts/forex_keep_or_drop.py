"""R-FX6 (V6.0.0, owner decision D3): keep the forex sleeve or drop it? Pre-registered rule.

BT2 (Lean, 3.25 years): the capped carry sleeve earned -$188 gross and paid $356 of IB minimums (~11 bps a fill on ~$1.8k
tickets): -$544 net. This re-runs the sleeve grid on the Lean-calibrated cost model (per-order dollar minimum, one-bar entry
lag, the dataset's own carry / momentum columns, late-bar lag like live) on validation, backtest and the whole Lean span
(backtest + holdout rows, the holdout seen and only used for the P&L clause):

    signal {carry, carry_momentum} x gross {0.10, 0.20, 0.30} x per_side {1, 2} x rebalance {20, 40} x deadband {$1k, $2.5k}

R-FX6: take the variant with the best VALIDATION net Sharpe. KEEP the sleeve (with that variant's keys) iff its net Sharpe is
> 0 on validation AND on the backtest split AND its simulated net return over the whole span 2023-07..2026-09 is > 0.
Otherwise DROP it: `forex_risk.enabled = false` (the clean switch: it also turns off the sleeve, its guard and the pairs'
book eligibility; forex bars keep feeding the cross-asset features).

    python scripts/forex_keep_or_drop.py --dataset ml/datasets/full_dataset.csv -> ml/evaluation/v600/forex_research.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))
sys.path.insert(0, str(Path(__file__).resolve().parent))

SIGNALS = ("carry", "carry_momentum")
GROSSES = (0.10, 0.20, 0.30)
PER_SIDES = (1, 2)
REBALANCES = (20, 40)
DEADBANDS = (1000.0, 2500.0)
FEE_BPS, MIN_USD = 0.2, 2.0


def decide(grid: dict) -> dict:
    """R-FX6 over {variant: {"validation": {"net_sharpe"}, "backtest": {"net_sharpe"}, "span": {"net_return"}}}."""
    best = max(grid, key=lambda name: grid[name]["validation"]["net_sharpe"])
    entry = grid[best]
    checks = {
        "validation_sharpe_positive": entry["validation"]["net_sharpe"] > 0.0,
        "backtest_sharpe_positive": entry["backtest"]["net_sharpe"] > 0.0,
        "span_net_return_positive": entry["span"]["net_return"] > 0.0,
    }
    if all(checks.values()):
        return {"branch": "keep", "variant": best, "checks": checks}
    return {"branch": "drop", "best_validation_variant": best, "checks": checks,
            "action": "phase_v2.forex_risk.enabled=false (also forex_sleeve.enabled and sleeve_guards.forex.enabled)"}


def parse_variant(name: str) -> dict:
    """`carry k=2 gross=0.1 reb=20 deadband=$1000` -> the sleeve keys it stands for."""
    signal, *rest = name.split()
    values = dict(token.split("=") for token in rest)
    return {"signal": signal, "per_side": int(values["k"]), "gross_budget": float(values["gross"]),
            "rebalance_every_bars": int(values["reb"]), "min_trade_usd": float(values["deadband"].lstrip("$"))}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dataset", default=str(ROOT_DIR / "ml" / "datasets" / "full_dataset.csv"))
    parser.add_argument("--out", default=str(ROOT_DIR / "ml" / "evaluation" / "v600" / "forex_research.json"))
    args = parser.parse_args()

    from as_live_levers import AsLiveHarness
    from class_sleeve_research import add_signal_columns, class_rank_ic, sleeve_run

    from evaluation.live_parity import lag_predictions_for_tickers

    grid: dict = {}
    ic: dict = {}
    for label, splits in (("validation", ("validation",)), ("backtest", ("backtest",)), ("span", ("backtest", "holdout"))):
        harness = AsLiveHarness(splits, dataset_path=Path(args.dataset))
        members = {t for t, kind in harness.asset_class_by_ticker.items() if kind == "forex"}
        frame = add_signal_columns(harness.frame, "forex")
        frame = frame[frame["ticker"].isin(members)].reset_index(drop=True)
        for column in [c for c in frame.columns if c.startswith("sig_")]:
            frame = lag_predictions_for_tickers(frame, prediction_column=column, tickers=members)
        ic[label] = {s: class_rank_ic(frame, f"sig_{s}", 4) for s in SIGNALS}
        for signal in SIGNALS:
            for per_side in PER_SIDES:
                for gross in GROSSES:
                    for rebalance in REBALANCES:
                        for deadband in DEADBANDS:
                            name = f"{signal} k={per_side} gross={gross} reb={rebalance} deadband=${deadband:.0f}"
                            run = sleeve_run(frame, harness.base, f"sig_{signal}", per_side=per_side, gross=gross, min_trade_usd=deadband,
                                             fee_bps=FEE_BPS, min_usd=MIN_USD, rebalance=rebalance)
                            grid.setdefault(name, {})[label] = {"net_sharpe": run.net_sharpe, "net_return": run.net_total_return,
                                                               "max_dd": run.net_max_drawdown, "cost_drag_bps": run.cost_drag_annual_bps}
        print(f"[{label}] done; carry IC {ic[label]['carry']}", flush=True)
        del harness, frame
    complete = {name: entry for name, entry in grid.items() if {"validation", "backtest", "span"} <= set(entry)}
    decision = decide(complete)
    best = decision.get("variant") or decision.get("best_validation_variant")
    print(f"best by validation: {best}", json.dumps(complete[best]))
    if decision["branch"] == "keep":
        decision["keys"] = parse_variant(decision["variant"])
    print("R-FX6:", json.dumps(decision))
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps({"ic": ic, "grid": complete, "decision": decision}, indent=1, default=float), encoding="utf-8")
    print(f"written {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
