"""How often does the shipped book end a rebalance with a sector above `sector_max_net_weight`? (V6.4.3, the
`sector_cap_counterexample` of formal/AetherFormal/BookNeutrality.lean.)

Replays `portfolio.book_neutrality.apply_book_neutrality` on every logged rebalance of a Lean run's book history: the raw
weights are rebuilt from the logged allocations with `build_book_raw_weights` (live's own pre-neutrality formula), then
neutralised with the run's config, once as shipped and once with `reapply_sector_cap_after_dollar_neutral`.

    python scripts/v643_sector_cap_frequency.py [--run backtests/2026-10-22_10-56-13 ...] [--out ml/evaluation/v643/sector_cap_frequency.json]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))

DEFAULT_RUNS = ("backtests/2026-10-22_10-56-13", "backtests/2026-10-24_05-28-07", "backtests/2026-10-24_18-50-22")


def replay_run(run_dir: Path) -> dict:
    from evaluation.lean_attribution import find_book_history_for_run, run_config_path
    from features import load_sector_mapping
    from portfolio.book_construction import BookAllocation, build_book_raw_weights
    from portfolio.book_neutrality import apply_book_neutrality

    config_path = run_config_path(run_dir, ROOT_DIR) or ROOT_DIR / "config.json"
    config = json.loads(Path(config_path).read_text(encoding="utf-8"))
    neutrality = config["phase_v2"]["portfolio_book"].get("neutrality", {})
    max_position_weight = float(config.get("phase6", {}).get("risk", {}).get("max_position_weight", 0.25))  # main.py's read
    sectors = load_sector_mapping(config)
    history_path = find_book_history_for_run(run_dir, ROOT_DIR / "visualization" / "book_history")
    records = [json.loads(line) for line in history_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    kwargs = dict(dollar_neutral=bool(neutrality.get("dollar_neutral", True)), sector_neutral=bool(neutrality.get("sector_neutral", True)),
                  gross_exposure_cap=float(neutrality.get("gross_exposure_cap", 1.0)),
                  max_weight_per_name=float(neutrality.get("max_weight_per_name", 0.12)),
                  sector_max_net_weight=float(neutrality.get("sector_max_net_weight", 0.15)))
    cap = kwargs["sector_max_net_weight"]
    rebalances = breaches = 0
    worst, l1_change, net_after_reapply = 0.0, [], []
    for record in records:
        allocations = record.get("allocations") or {}
        if not allocations:
            continue
        book = {symbol: BookAllocation(role=entry["role"], book_role_multiplier=float(entry["book_role_multiplier"]),
                                       predicted_rank_20d=float(entry["predicted_rank_20d"]), book_reason="replay")
                for symbol, entry in allocations.items()}
        raw = build_book_raw_weights(book, max_position_weight)
        sector_by_symbol = {symbol: allocations[symbol].get("sector") or sectors.get(symbol, "Unknown") for symbol in raw}
        shipped, diagnostics = apply_book_neutrality(raw, sector_by_symbol=sector_by_symbol, **kwargs)
        reapplied, reapplied_diagnostics = apply_book_neutrality(raw, sector_by_symbol=sector_by_symbol,
                                                                 reapply_sector_cap_after_dollar_neutral=True, **kwargs)
        rebalances += 1
        over = max((abs(net) - cap for net in diagnostics["per_sector_net"].values()), default=0.0)
        if over > 1e-12:
            breaches += 1
            worst = max(worst, over)
        l1_change.append(sum(abs(shipped[s] - reapplied[s]) for s in shipped))
        net_after_reapply.append(abs(reapplied_diagnostics["net_after"]))
    return {"run": run_dir.name, "config": str(config_path), "rebalances": rebalances, "breaching_rebalances": breaches,
            "breach_share": breaches / rebalances if rebalances else None, "worst_excess_over_cap": worst,
            "sector_max_net_weight": cap, "mean_l1_change_with_reapply": sum(l1_change) / len(l1_change) if l1_change else None,
            "max_abs_net_with_reapply": max(net_after_reapply, default=0.0)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--run", action="append", default=None)
    parser.add_argument("--out", default=str(ROOT_DIR / "ml" / "evaluation" / "v643" / "sector_cap_frequency.json"))
    args = parser.parse_args()
    runs = [ROOT_DIR / run for run in (args.run or DEFAULT_RUNS)]
    report = {"runs": [replay_run(run) for run in runs]}
    for row in report["runs"]:
        print(json.dumps(row))
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
