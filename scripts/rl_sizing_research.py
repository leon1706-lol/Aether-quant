"""RL sizing research (V5.8.0): rule R-RL (offline half) and R-SLEEVE for the RL overlay.

The trainers say whether a policy beats constant 1.0 on its own reward (`policy_beats_constant_unpenalized`). That is the
first half of R-RL; the second half needs the policy inside the whole as-live book, which V5.8.0 made possible
(`evaluation/live_parity.build_live_member_weight_fn(rl_model=...)` applies the same `rl_sizing_multiplier` and the same
shadow guard as `main.py`). For each split this runs the as-live book

    baseline (no RL)  |  RL with several multiplier ranges  |  RL + shadow guard

and reports the Sharpe/return/drawdown deltas. Decision:

  * edge_pass   - the trainer verdict is true AND some range is >= +0.05 net Sharpe on BOTH splits: ship RL at that range;
  * otherwise   - owner decision (RL must be in use): ship RL at the minimum range [0.9, 1.1] with the shadow guard on,
                  which bounds what it can cost (it falls back to constant 1.0 while it trails it).

    python scripts/rl_sizing_research.py --rl-model ml/versions/<id>/rl_sizing_model.json
        [--trainer-metrics ml/versions/<id>/rl_sizing_training_metrics.json] [--dataset PATH] [--no-cache]
    -> ml/evaluation/rl_sizing_research.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from as_live_levers import AsLiveHarness, add_split_dataset_args, dataset_for_split, summarize  # noqa: E402

MIN_SHARPE_GAIN = 0.05
MINIMUM_RANGE = (0.9, 1.1)
RANGES = ((0.9, 1.1), (0.8, 1.0), (0.6, 1.0), (0.8, 1.2), (0.6, 1.2))
GUARD = {"enabled": True, "window_bars": 60, "tolerance_nav_fraction": 0.002}


def decide(trainer_beats_constant: bool | None, by_range: dict) -> dict:
    """`by_range` = {"lo-hi": {"validation": gain, "backtest": gain}} of net-Sharpe gains over the no-RL book."""
    passing = [name for name, gains in by_range.items()
               if gains["validation"] >= MIN_SHARPE_GAIN and gains["backtest"] >= MIN_SHARPE_GAIN]
    if trainer_beats_constant and passing:
        best = max(passing, key=lambda name: by_range[name]["validation"])
        low, high = (float(x) for x in best.split("-"))
        return {"branch": "edge_pass", "range": [low, high], "shadow_guard": False, "passing": sorted(passing)}
    return {"branch": "trade_anyway_minimum_range", "range": list(MINIMUM_RANGE), "shadow_guard": True,
            "reason": "trainer verdict false or no range gains >= +0.05 Sharpe on both splits"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--rl-model", required=True)
    parser.add_argument("--trainer-metrics", default=None)
    add_split_dataset_args(parser)
    parser.add_argument("--no-cache", action="store_true")
    args = parser.parse_args()

    trainer_beats = None
    if args.trainer_metrics:
        metrics = json.loads(Path(args.trainer_metrics).read_text(encoding="utf-8"))
        trainer_beats = metrics.get("policy_beats_constant_unpenalized")
    report: dict = {"rl_model": args.rl_model, "trainer_policy_beats_constant": trainer_beats, "splits": {}}
    gains: dict[str, dict] = {f"{lo}-{hi}": {} for lo, hi in RANGES}
    guarded_gains: dict[str, float] = {}
    for split in ("validation", "backtest"):
        harness = AsLiveHarness(
            split, use_cache=not args.no_cache, dataset_path=dataset_for_split(args, split), rl_model_path=args.rl_model
        )
        baseline = harness.as_live()
        report["splits"][split] = {"baseline": summarize(baseline), "ranges": {}}
        print(f"[{split}] no RL: {baseline.net_sharpe:+.3f}")
        for low, high in RANGES:
            overrides = {"dynamic_risk.rl_sizing_enabled": True, "dynamic_risk.min_rl_multiplier": low,
                         "dynamic_risk.max_rl_multiplier": high}
            run = harness.as_live(config_overrides=overrides)
            name = f"{low}-{high}"
            gains[name][split] = run.net_sharpe - baseline.net_sharpe
            report["splits"][split]["ranges"][name] = dict(summarize(run), sharpe_gain=gains[name][split])
            print(f"[{split}] RL {name}: {run.net_sharpe:+.3f} ({gains[name][split]:+.3f})")
        guarded = harness.as_live(config_overrides={
            "dynamic_risk.rl_sizing_enabled": True, "dynamic_risk.min_rl_multiplier": MINIMUM_RANGE[0],
            "dynamic_risk.max_rl_multiplier": MINIMUM_RANGE[1], "dynamic_risk.rl_shadow_guard": GUARD})
        guarded_gains[split] = guarded.net_sharpe - baseline.net_sharpe
        report["splits"][split]["minimum_range_with_shadow_guard"] = dict(summarize(guarded), sharpe_gain=guarded_gains[split])
        print(f"[{split}] RL {MINIMUM_RANGE} + shadow guard: {guarded.net_sharpe:+.3f} ({guarded_gains[split]:+.3f})")
    report["gains"] = gains
    report["decision"] = decide(trainer_beats, gains)
    print("decision:", json.dumps(report["decision"]))
    out = ROOT_DIR / "ml" / "evaluation" / "rl_sizing_research.json"
    out.write_text(json.dumps(report, indent=2, default=float), encoding="utf-8")
    print(f"written {out}")

    from evaluation.readme_research import refresh_readme_best_effort

    refresh_readme_best_effort()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
