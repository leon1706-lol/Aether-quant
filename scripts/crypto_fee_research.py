"""R-CRYPTO (V6.0.0, todo lead 3): what to do about the crypto exchange fee? Pre-registered rule.

BT2 paid $1,131 of Coinbase fees on $775 of gross crypto P&L: limit fills (entries) pay 60 bps, market fills (every exit,
every timeout fallback) 80 bps. Two levers are built: limit EXITS (`phase_v2.limit_orders.exit_asset_classes`) and fewer /
smaller graduate pairs. On the Lean-calibrated simulator (`scripts/lean_calibration.py`), per split:

    C0 current: limit entries, market exits (fee priced route-aware: entry maker, exit taker)
    C1 + limit exits at the configured offset / timeout           C3 graduates off (BTCUSD / LTCUSD only)
    C2 + the best offset / timeout of the fill sweep              C4 graduates at 0.5% per name / 2.5% class
    C5 C2 + the better of C3 / C4 (by validation crypto net)

The fill rates come from `evaluation.limit_fill_simulator` on the crypto rows (entry side measured in BT2: 109 of 112 limit
orders filled). A resting order is not priced for price improvement (conservative). Crypto component P&L = the crypto names'
weights x next-day returns minus per-side fees on their weight changes, from the simulator's weight log.

R-CRYPTO: pick the variant with the best VALIDATION crypto-component net that (1) leaves the total-book backtest Sharpe not
worse than C0 by more than 0.05, (2) has a simulated limit fill rate >= 85% on every limit side it routes, and (3) keeps
BTCUSD / LTCUSD tradable; if no variant beats C0's validation crypto net, C0 stays. The Lean check is BT1's realised fee per
fill by route (`aq evaluate --attribute-lean`).

    python scripts/crypto_fee_research.py --dataset ml/datasets/full_dataset.csv -> ml/evaluation/v600/crypto_research.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))
sys.path.insert(0, str(Path(__file__).resolve().parent))

MAKER_BPS, TAKER_BPS = 60.0, 80.0
ENTRY_FILL_RATE_BT2 = 109 / 112  # limit crypto orders that filled in BT2 (3 timed out)
MIN_FILL_RATE = 0.85
MAX_TOTAL_BOOK_LOSS = 0.05
OFFSETS = (0.0, 0.5, 1.0)
TIMEOUTS = (3, 5)
CORE = ("BTCUSD", "LTCUSD")


def component_net(result, frame, tickers: set[str], fee_bps: float) -> dict:
    """Net return (fraction of NAV) of `tickers`' positions inside a simulated book: gross P&L from the previous date's
    weights (one-bar entry lag) x the date's return, fees on every weight change at `fee_bps` per side."""
    dates = list(result.per_date)
    returns = frame.set_index(["date", "ticker"])["target_return_1d"].to_dict()
    gross = fees = 0.0
    previous: dict[str, float] = {}
    for index, date in enumerate(dates):
        current = {ticker: weight for ticker, weight in result.weights_log[index].items() if ticker in tickers}
        if index > 0:
            gross += sum(weight * float(returns.get((date, ticker), 0.0) or 0.0) for ticker, weight in previous.items())
        fees += sum(abs(current.get(ticker, 0.0) - previous.get(ticker, 0.0)) for ticker in set(current) | set(previous)) * fee_bps / 1e4
        previous = current
    return {"gross": gross, "fees": fees, "net": gross - fees}


def fill_rates(frame, offset: float, timeout: int) -> dict:
    from evaluation.limit_fill_simulator import simulate_limit_fills

    crypto = frame[frame["ticker"].isin(frame.attrs["crypto_tickers"])]
    sim = simulate_limit_fills(crypto, unfilled_timeout_bars=timeout, offset_multiplier=offset)
    return {"overall": sim["overall"]["fill_rate"], "buy": sim["by_side"]["buy"]["fill_rate"], "sell": sim["by_side"]["sell"]["fill_rate"],
            "mean_bars_to_fill": sim["overall"]["mean_bars_to_fill"]}


def fee_per_side(entry_limit: bool, exit_limit: bool, entry_rate: float, exit_rate: float) -> float:
    from execution.cost_model import route_aware_per_side_fee_bps

    return route_aware_per_side_fee_bps({"maker_bps": MAKER_BPS, "taker_bps": TAKER_BPS, "entry_limit": entry_limit,
                                         "exit_limit": exit_limit, "fill_rate": entry_rate, "exit_fill_rate": exit_rate})


def decide(results: dict, fill: dict) -> dict:
    """R-CRYPTO on {variant: {split: {"crypto_net", "total_sharpe"}}} and {variant: min fill rate of the sides it routes}."""
    base = results["C0"]
    eligible = []
    for name, row in results.items():
        if name == "C0":
            continue
        checks = {
            "total_book_backtest_not_worse_than_0.05": row["backtest"]["total_sharpe"] - base["backtest"]["total_sharpe"] >= -MAX_TOTAL_BOOK_LOSS,
            "fill_rate_ge_85": fill.get(name, 1.0) >= MIN_FILL_RATE,
            "core_tradable": True,
            "beats_C0_validation_crypto_net": row["validation"]["crypto_net"] > base["validation"]["crypto_net"],
        }
        if all(checks.values()):
            eligible.append((row["validation"]["crypto_net"], name))
    if not eligible:
        return {"winner": "C0", "reason": "no variant beats C0's validation crypto net inside the constraints"}
    return {"winner": max(eligible)[1], "eligible": sorted(name for _, name in eligible)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dataset", default=str(ROOT_DIR / "ml" / "datasets" / "full_dataset.csv"))
    parser.add_argument("--out", default=str(ROOT_DIR / "ml" / "evaluation" / "v600" / "crypto_research.json"))
    args = parser.parse_args()

    from as_live_levers import AsLiveHarness, summarize
    from lean_calibration import calibrated_overrides, topology_inputs_fn_for, use_topology

    from execution.cost_model import commission_bps_by_ticker
    from portfolio.book_construction import resolve_class_weight_caps
    from risk.asset_class_router import load_venue_listing_dates

    config = json.loads((ROOT_DIR / "config.json").read_text(encoding="utf-8"))
    security_types = {str(a["ticker"]): str(a["security_type"]) for a in config["phase1"]["universe"]["assets"]}
    listing = load_venue_listing_dates(ROOT_DIR / "data" / "reference" / "crypto_listing_dates.json")
    harnesses = {}
    for split in ("validation", "backtest"):
        harness = AsLiveHarness(split, dataset_path=Path(args.dataset))
        harness.venue_listing_dates = listing or None
        harnesses[split] = (harness, topology_inputs_fn_for(harness, harness.config))
    crypto_all = sorted(t for t, kind in harnesses["backtest"][0].asset_class_by_ticker.items() if kind == "crypto")
    for harness, _ in harnesses.values():
        harness.frame.attrs["crypto_tickers"] = crypto_all

    sweep = {}
    for timeout in TIMEOUTS:
        for offset in OFFSETS:
            sweep[f"offset{offset}_timeout{timeout}"] = {
                split: fill_rates(harnesses[split][0].frame, offset, timeout) for split in harnesses
            }
            row = sweep[f"offset{offset}_timeout{timeout}"]
            print(f"fill sweep offset {offset} timeout {timeout}: " + " | ".join(f"{s} buy {v['buy']:.3f} sell {v['sell']:.3f}" for s, v in row.items()), flush=True)

    def mean_side(name: str, side: str) -> float:
        return float(np.mean([sweep[name][split][side] for split in harnesses]))

    current_key = f"offset{float(config['phase_v2']['limit_orders']['offset_multiplier'])}_timeout{int(config['phase_v2']['limit_orders']['unfilled_timeout_bars'])}"
    best_key = max((k for k in sweep if mean_side(k, "sell") >= MIN_FILL_RATE), key=lambda k: mean_side(k, "sell"), default=current_key)
    graduates = sorted(set(crypto_all) - set(CORE))

    def variant(name: str, *, exit_limit: bool, sweep_key: str, graduates_on: bool = True, caps=(0.01, 0.05)) -> dict:
        exit_rate = mean_side(sweep_key, "sell")
        fee = fee_per_side(True, exit_limit, ENTRY_FILL_RATE_BT2, exit_rate)
        fee_map = {ticker: fee for ticker in crypto_all}
        out = {}
        for split, (harness, topology_fn) in harnesses.items():
            use_topology(harness, topology_fn)
            metadata = {t: dict(v) for t, v in harness.metadata.items()}
            if not graduates_on:
                for ticker in graduates:
                    metadata[ticker]["trading_eligible"] = False
            cap_config = resolve_class_weight_caps({"crypto": {"per_name_cap": caps[0], "class_gross_cap": caps[1], "exempt": list(CORE)}})
            base_fees = commission_bps_by_ticker(harness.config["phase_v2"].get("costs", {}), security_types)
            fees = {**base_fees, **fee_map}
            result = harness.as_live(
                log_weights=True, candidate_metadata_by_ticker=metadata, class_weight_caps=cap_config,
                commission_bps_by_ticker=fees, **calibrated_overrides(harness),
            )
            summary = summarize(result)
            crypto = component_net(result, harness.frame, set(crypto_all), fee)
            out[split] = {"total_sharpe": summary["net_sharpe"], "total_return": summary["net_total_return"], "crypto_net": crypto["net"],
                          "crypto_gross": crypto["gross"], "crypto_fees": crypto["fees"]}
        out["fee_per_side_bps"] = fee
        print(f"{name}: fee/side {fee:.1f} bps | " + " | ".join(
            f"{s} crypto net {out[s]['crypto_net']:+.4f} (gross {out[s]['crypto_gross']:+.4f}, fees {out[s]['crypto_fees']:.4f}) total sharpe {out[s]['total_sharpe']:+.3f}"
            for s in harnesses), flush=True)
        return out

    results = {
        "C0": variant("C0", exit_limit=False, sweep_key=current_key),
        "C1": variant("C1", exit_limit=True, sweep_key=current_key),
        "C2": variant("C2", exit_limit=True, sweep_key=best_key),
        "C3": variant("C3", exit_limit=False, sweep_key=current_key, graduates_on=False),
        "C4": variant("C4", exit_limit=False, sweep_key=current_key, caps=(0.005, 0.025)),
    }
    better = "C3" if results["C3"]["validation"]["crypto_net"] >= results["C4"]["validation"]["crypto_net"] else "C4"
    results["C5"] = variant("C5", exit_limit=True, sweep_key=best_key, graduates_on=(better != "C3"),
                            caps=(0.005, 0.025) if better == "C4" else (0.01, 0.05))
    fill = {"C1": mean_side(current_key, "sell"), "C2": mean_side(best_key, "sell"), "C5": mean_side(best_key, "sell")}
    decision = decide(results, fill)
    decision.update(best_sweep=best_key, current_sweep=current_key, combined_with=better)
    print("R-CRYPTO:", json.dumps(decision))
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps({"sweep": sweep, "results": results, "fill_rates_routed": fill, "decision": decision},
                                         indent=1, default=float), encoding="utf-8")
    print(f"written {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
