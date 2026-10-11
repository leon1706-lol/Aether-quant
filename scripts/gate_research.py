"""V5.7.0 gate research: every gate / lever decision of todo.md findings 1-6 on BOTH splits with the full as-live
simulator (kill switch, member sizing chain, liquidity and net-edge gates, per-name impact).

For each experiment the net Sharpe, return, drawdown and gate counts are reported on the backtest split (the window Lean
also tests: an upper estimate) and on the validation split (the only independent evidence), next to the config baseline.
The decision rule (R-GATE in the V5.7.0 plan) is applied by `decide()`:

    flip only if backtest net Sharpe improves by >= 0.10, validation net Sharpe does not fall by more than 0.02, and the
    max drawdown is not worse by more than 1.0 pp on either split; among passing values take the best validation Sharpe.

    python scripts/gate_research.py [--group kill_switch spread ic_gate hold hrp impact] [--no-cache]

Writes ml/evaluation/v570_gate_research.json.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from as_live_levers import AsLiveHarness, summarize  # noqa: E402

MIN_BACKTEST_GAIN = 0.10
MAX_VALIDATION_LOSS = 0.02
MAX_DRAWDOWN_WORSENING = 0.01  # fraction: 1.0 pp


def decide(baseline: dict, candidate: dict) -> dict:
    """R-GATE on two {"backtest": summary, "validation": summary} dicts."""
    backtest_gain = candidate["backtest"]["net_sharpe"] - baseline["backtest"]["net_sharpe"]
    validation_gain = candidate["validation"]["net_sharpe"] - baseline["validation"]["net_sharpe"]
    drawdown_worse = {
        split: baseline[split]["net_max_drawdown"] - candidate[split]["net_max_drawdown"]  # drawdowns are negative
        for split in ("backtest", "validation")
    }
    passes = (
        backtest_gain >= MIN_BACKTEST_GAIN
        and validation_gain >= -MAX_VALIDATION_LOSS
        and all(worse <= MAX_DRAWDOWN_WORSENING for worse in drawdown_worse.values())
    )
    return {
        "backtest_sharpe_gain": round(backtest_gain, 4), "validation_sharpe_gain": round(validation_gain, 4),
        "drawdown_worsening_pp": {split: round(100 * worse, 3) for split, worse in drawdown_worse.items()},
        "passes_r_gate": bool(passes),
    }


def experiments(harnesses: dict[str, AsLiveHarness]) -> dict[str, dict[str, callable]]:
    """{group: {name: callable(harness) -> result}}."""
    ks = "risk.kill_switch"
    groups: dict[str, dict[str, callable]] = {"baseline": {"as-live (config)": lambda h: h.as_live()}}

    kill = {"kill switch off": lambda h: h.as_live(include=("member_sizing", "hrp", "impact"))}
    for floor in (-1.0, -1.5, -2.0):
        for bars in (60, 120):
            for std in (0.0005, 0.001):
                kill[f"ks sharpe<{floor} bars={bars} std>{std}"] = (
                    lambda h, floor=floor, bars=bars, std=std: h.as_live(config_overrides={
                        f"{ks}.min_rolling_sharpe": floor, f"{ks}.evaluation_bars": bars, f"{ks}.min_return_std_for_sharpe": std,
                    })
                )
    groups["kill_switch"] = kill

    spread = {}
    for floor in (0.0, 0.10, 0.15, 0.1985, 0.25, 0.2831):
        spread[f"spread floor {floor}"] = lambda h, floor=floor: h.as_live(min_rank_confidence_spread=floor)
    groups["spread"] = spread

    ic = {"ic gate off": lambda h: h.as_live(gate="off")}
    for horizon, window in ((20, 40), (20, 80), (20, 120), (5, 40), (5, 80)):
        for floor in (0.0, 0.02, 0.05):
            ic[f"ic h={horizon} w={window} floor={floor}"] = (
                lambda h, horizon=horizon, window=window, floor=floor: h.as_live(
                    ic_floor=floor, gate_horizon=horizon, gate_window=window,
                    config_overrides={"rolling_ic_gate.min_resolved_dates_required": min(window, 40)},
                )
            )
    groups["ic_gate"] = ic

    groups["hold"] = {
        "hold-on-veto off (anchor kept)": lambda h: h.as_live(hold_positions_on_veto=False),
        "hold-on-veto off (anchor off)": lambda h: h.as_live(hold_positions_on_veto=False, hysteresis_anchor_on_formed_book=False),
    }
    groups["hrp"] = {"hrp allocation": lambda h: h.as_live(config_overrides={"portfolio_book.allocation_method": "hrp"})}
    groups["impact"] = {"as-live with Almgren impact": lambda h: h.as_live(
        impact_model_config={"enabled": True, "eta": 0.5}
    )}
    return groups


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--group", nargs="*", default=None)
    parser.add_argument("--no-cache", action="store_true")
    args = parser.parse_args()

    harnesses = {split: AsLiveHarness(split, use_cache=not args.no_cache) for split in ("backtest", "validation")}
    groups = experiments(harnesses)
    selected = args.group or [name for name in groups if name != "baseline"]
    results: dict[str, dict] = {}
    for group in ["baseline", *selected]:
        for name, run in groups[group].items():
            per_split = {split: summarize(run(harness)) for split, harness in harnesses.items()}
            results[name] = {"group": group, **per_split}
            print(
                f"[{group}] {name:44s} "
                + " | ".join(
                    f"{split[:4]} sharpe {per_split[split]['net_sharpe']:+.3f} ret {100 * per_split[split]['net_total_return']:+.2f}% "
                    f"dd {100 * per_split[split]['net_max_drawdown']:.2f}% ks {per_split[split]['kill_switch_locked_dates']}"
                    for split in per_split
                ),
                flush=True,
            )
    baseline = results["as-live (config)"]
    for name, entry in results.items():
        if name != "as-live (config)":
            entry["decision"] = decide(baseline, entry)
    out = ROOT_DIR / "ml" / "evaluation" / "v570_gate_research.json"
    out.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"written {out}")
    # Switching a safety control off (kill switch, whole IC gate) is reported but never a candidate winner: R-GATE tunes
    # a control's value, it does not remove it.
    winners = sorted(
        (
            (name, entry["decision"])
            for name, entry in results.items()
            if entry.get("decision", {}).get("passes_r_gate") and not name.endswith(" off")
        ),
        key=lambda item: -results[item[0]]["validation"]["net_sharpe"],
    )
    print("R-GATE passes:", [name for name, _ in winners] or "none")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
