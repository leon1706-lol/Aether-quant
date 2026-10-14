"""Crypto graduates: which of the extra crypto pairs trade, and at what cap? (V5.7.0 question, rebuilt for V5.8.0)

V5.7.0 asked whether any observation-only pair should JOIN the two core names (BTCUSD, LTCUSD); none passed R-GATE
(Problems.md #149). With the data window extended to 2026 every pair has >= 1,400 train rows, so all twelve are
trading-eligible and the owner's decision is that they trade — capped when the evidence is not there. This measures, on
BOTH splits with the full as-live simulator, Coinbase fees and the venue listing guard (no order before a pair's Coinbase
listing, none while it is suspended or after a delisting):

    core_only                       the V5.7.0 state: only BTCUSD/LTCUSD can be selected
    all_uncapped                    every eligible crypto pair, no class caps
    capped <per-name>/<class-gross> every eligible pair with `class_weight_caps` (core exempt)
    leave-one-out                   the best capped configuration without one graduate at a time

R-SLEEVE: a capped configuration that passes R-GATE against `core_only` ships at its researched cap ("edge_pass");
otherwise the graduates ship at the minimum cap (per-name 1%, class gross 5%) with the crypto-graduates loss guard
("trade_anyway_minimum_cap") and the numbers say which branch fired.

    python scripts/crypto_graduation_research.py [--dataset-validation PATH --dataset-backtest PATH] [--no-cache]  -> ml/evaluation/crypto_graduation_research.json
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
from gate_research import decide as r_gate  # noqa: E402

from portfolio.book_construction import resolve_class_weight_caps  # noqa: E402
from risk.asset_class_router import load_venue_listing_dates  # noqa: E402

CORE = ("BTCUSD", "LTCUSD")
CAP_GRID = ((0.01, 0.05), (0.02, 0.05), (0.02, 0.10), (0.04, 0.10))
MINIMUM_CAP = (0.01, 0.05)


def caps_for(per_name: float, class_gross: float) -> dict:
    return resolve_class_weight_caps({"crypto": {"per_name_cap": per_name, "class_gross_cap": class_gross, "exempt": list(CORE)}})


def run(harness: AsLiveHarness, *, eligible: set[str], caps: dict | None):
    """One as-live run where exactly `eligible` crypto names (plus every non-crypto name as configured) can be selected."""
    metadata = {t: dict(v) for t, v in harness.metadata.items()}
    for ticker, kind in harness.asset_class_by_ticker.items():
        if kind == "crypto":
            metadata[ticker]["trading_eligible"] = ticker in eligible
    harness.core_crypto = frozenset(harness.core_crypto) | frozenset(eligible)
    harness._mechanisms.clear()
    return harness.as_live(candidate_metadata_by_ticker=metadata, class_weight_caps=caps or None)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_split_dataset_args(parser)
    parser.add_argument("--no-cache", action="store_true")
    args = parser.parse_args()

    listing = load_venue_listing_dates(ROOT_DIR / "data" / "reference" / "crypto_listing_dates.json")
    harnesses = {}
    for split in ("backtest", "validation"):
        harness = AsLiveHarness(split, use_cache=not args.no_cache, dataset_path=dataset_for_split(args, split))
        harness.venue_listing_dates = listing or None  # always on for this research, whatever the config says
        harnesses[split] = harness
    reference = harnesses["backtest"]
    all_crypto = sorted(t for t, kind in reference.asset_class_by_ticker.items() if kind == "crypto")
    manifest_eligible = {t for t in all_crypto if reference.metadata[t]["trading_eligible"]}
    present = set.intersection(*[set(h.frame["ticker"].unique()) for h in harnesses.values()])
    graduates = sorted(t for t in manifest_eligible if t not in CORE and t in present)
    print("crypto graduates with rows on both splits:", graduates)

    experiments: dict[str, tuple[set[str], dict | None]] = {
        "core_only": (set(CORE) & manifest_eligible, None),
        "all_uncapped": (set(CORE) | set(graduates), None),
    }
    for per_name, class_gross in CAP_GRID:
        experiments[f"capped {per_name}/{class_gross}"] = (set(CORE) | set(graduates), caps_for(per_name, class_gross))
    results: dict[str, dict] = {}
    for name, (eligible, caps) in experiments.items():
        results[name] = {split: summarize(run(h, eligible=eligible, caps=caps)) for split, h in harnesses.items()}
        print(name.ljust(24) + " | ".join(
            f"{split[:4]} sharpe {results[name][split]['net_sharpe']:+.3f} ret {100 * results[name][split]['net_total_return']:+.2f}% "
            f"dd {100 * results[name][split]['net_max_drawdown']:.2f}%" for split in results[name]), flush=True)
    for name in results:
        if name != "core_only":
            results[name]["r_gate_vs_core_only"] = r_gate(results["core_only"], results[name])

    passing = [n for n in results if n.startswith("capped") and results[n]["r_gate_vs_core_only"]["passes_r_gate"]]
    best_capped = max(
        (n for n in results if n.startswith("capped")), key=lambda n: results[n]["validation"]["net_sharpe"] + results[n]["backtest"]["net_sharpe"]
    )
    chosen = max(passing, key=lambda n: results[n]["validation"]["net_sharpe"]) if passing else None
    reference_name = chosen or f"capped {MINIMUM_CAP[0]}/{MINIMUM_CAP[1]}"
    reference_caps = experiments[reference_name][1]
    leave_one_out = {}
    for ticker in graduates:
        eligible = (set(CORE) | set(graduates)) - {ticker}
        leave_one_out[ticker] = {split: summarize(run(h, eligible=eligible, caps=reference_caps)) for split, h in harnesses.items()}
        leave_one_out[ticker]["r_gate_vs_reference"] = r_gate(results[reference_name], leave_one_out[ticker])
        print(f"without {ticker:8s} " + " | ".join(
            f"{split[:4]} sharpe {leave_one_out[ticker][split]['net_sharpe']:+.3f}" for split in ("backtest", "validation")), flush=True)
    if chosen:
        decision = {"branch": "edge_pass", "config": chosen, "per_name_cap": float(chosen.split()[1].split("/")[0]),
                    "class_gross_cap": float(chosen.split("/")[1]), "passing": sorted(passing)}
    else:
        decision = {"branch": "trade_anyway_minimum_cap", "per_name_cap": MINIMUM_CAP[0], "class_gross_cap": MINIMUM_CAP[1],
                    "loss_guard": True, "best_capped_config": best_capped,
                    "reason": "no capped configuration passes R-GATE against the core-only book on both splits"}
    names_that_hurt = sorted(t for t, entry in leave_one_out.items() if entry["r_gate_vs_reference"]["passes_r_gate"])
    print("decision:", json.dumps(decision), "| removing these would pass R-GATE (reported, not applied):", names_that_hurt or "none")
    out = ROOT_DIR / "ml" / "evaluation" / "crypto_graduation_research.json"
    out.write_text(json.dumps({"graduates": graduates, "results": results, "leave_one_out": leave_one_out, "decision": decision,
                               "removal_would_pass_r_gate": names_that_hurt}, indent=2, default=float), encoding="utf-8")
    print(f"written {out}")

    from evaluation.readme_research import refresh_readme_best_effort

    refresh_readme_best_effort()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
