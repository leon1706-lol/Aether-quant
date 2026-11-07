"""R-GLIDE1 on the PC: its rule hashed before any run, then the policies over fixed-seed worlds; the winner goes to ml/generations/glide_policy.json and the policy file. Also the decay detector's run lengths.

    python scripts/v661_glide.py rules
    python scripts/v661_glide.py run [--paths 2000]
    python scripts/v661_glide.py decay
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from evaluation.alpha_decay import average_run_lengths  # noqa: E402
from evaluation.glide_calibration import (  # noqa: E402
    default_configs,
    default_policies,
    evaluate_policies,
    glide2_policies,
    pick_glide2,
    pick_policy,
)

OUT = ROOT / "ml" / "generations"
RULES = OUT / "rules_glide1.json"
R_GLIDE1 = (
    "Monte Carlo, 2,000 fixed-seed paths: a new generation each year, Sharpe {0.5, 1.0}, alpha half-life {1, 2, 3} years, return correlation {0, 0.3, 0.6}, probability a new generation has zero alpha {0.5, 0.8}, "
    "costs and the 0.002 deadband on. Policies: instant switch, equal weight, fixed glide {126, 252, 504}, ladder with evidence multiplier {none, hold on watch, accelerate on decaying}. Pick the lowest median regret "
    "against the oracle among policies whose time above 50% of capital on a zero-alpha generation is <= 20%. Ties go to fewer parameters. Replay on real score files is report-only, because ml/versions holds no real "
    "vintages. No policy qualifying: fixed 252."
)


def stage_rules() -> int:
    if RULES.exists():
        raise SystemExit("the rule is written once")
    payload = {"rule": "R-GLIDE1", "text": R_GLIDE1, "configs": default_configs(), "policies": default_policies(), "seed": 1, "paths": 2000, "years": 8, "tie": 0.005, "max_zero_alpha_share": 0.20}
    OUT.mkdir(parents=True, exist_ok=True)
    RULES.write_text(json.dumps(payload, indent=1) + "\n", encoding="utf-8", newline="\n")
    RULES.with_suffix(".sha256").write_text(hashlib.sha256(RULES.read_bytes()).hexdigest() + "\n", encoding="utf-8", newline="\n")
    print(RULES.with_suffix(".sha256").read_text(encoding="utf-8").strip())
    return 0


def stage_run(paths: int) -> int:
    payload = json.loads(RULES.read_text(encoding="utf-8"))
    if hashlib.sha256(RULES.read_bytes()).hexdigest() != RULES.with_suffix(".sha256").read_text(encoding="utf-8").strip():
        raise SystemExit("rules_glide1.json is not the recorded hash")
    results = evaluate_policies(payload["configs"], payload["policies"], paths=paths, seed=int(payload["seed"]), years=int(payload["years"]))
    chosen = pick_policy(results, max_zero_alpha_share=float(payload["max_zero_alpha_share"]), tie=float(payload["tie"]))
    chosen["paths_requested"] = paths
    out = OUT / "glide_policy.json"
    out.write_text(json.dumps(chosen, indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    picked = next(policy for policy in payload["policies"] if policy["name"] == chosen["policy"]) if any(policy["name"] == chosen["policy"] for policy in payload["policies"]) else {}
    policy_file = OUT / "policy.json"
    policy = json.loads(policy_file.read_text(encoding="utf-8"))
    for key in ("glide_sessions", "hold_on_watch", "accelerate_on_decaying"):
        if key in picked:
            policy["glide"][key] = picked[key]
    policy["glide_policy"] = chosen["policy"]
    policy_file.write_text(json.dumps(policy, indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    for name, row in sorted(results.items(), key=lambda item: item[1]["median_regret"]):
        print(f"{name:32s} regret {row['median_regret']:.3f}  on a zero-alpha generation {row['zero_alpha_majority_share']:.3f}")
    print("chosen:", chosen["policy"])
    return 0


RULES2 = OUT / "rules_glide2.json"
R_GLIDE2 = (
    "The worlds, seeds, costs and deadband of R-GLIDE1. Policies: fixed_252 (the installed result of R-GLIDE1), equal weight, and the dynamic mode over half life {63, 126}, prior sessions {126, 252, 504}, score floor {0, 0.2}, "
    "blend row every {5, 21} sessions, at most 4 generations holding capital. Among dynamic policies no worse than fixed_252 on time above 50% of capital on a zero-alpha generation, take the lowest median regret, ties within 0.005 "
    "to less turnover. It replaces fixed_252 if its regret is no worse than fixed_252's, within 0.005: the owner asked for this form on 2026-11-06, so no worse is enough. Otherwise fixed_252 stays and the dynamic mode remains an "
    "option the owner can select, with these numbers. R-GLIDE1's limit of 20% is reported, not moved. Every generation is judged against the same claim, its selection Sharpe halved."
)


def stage_rules2() -> int:
    if RULES2.exists():
        raise SystemExit("the rule is written once")
    payload = {"rule": "R-GLIDE2", "text": R_GLIDE2, "configs": default_configs(), "policies": glide2_policies(), "seed": 2, "paths": 2000, "years": 8, "tie": 0.005}
    RULES2.write_text(json.dumps(payload, indent=1) + "\n", encoding="utf-8", newline="\n")
    RULES2.with_suffix(".sha256").write_text(hashlib.sha256(RULES2.read_bytes()).hexdigest() + "\n", encoding="utf-8", newline="\n")
    print(RULES2.with_suffix(".sha256").read_text(encoding="utf-8").strip())
    return 0


def stage_run2(paths: int, workers: int) -> int:
    if hashlib.sha256(RULES2.read_bytes()).hexdigest() != RULES2.with_suffix(".sha256").read_text(encoding="utf-8").strip():
        raise SystemExit("rules_glide2.json is not the recorded hash")
    payload = json.loads(RULES2.read_text(encoding="utf-8"))
    results = evaluate_policies(payload["configs"], payload["policies"], paths=paths, seed=int(payload["seed"]), years=int(payload["years"]), workers=workers)
    chosen = pick_glide2(results, tie=float(payload["tie"]))
    (OUT / "glide2_policy.json").write_text(json.dumps({**chosen, "results": results}, indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    policy_file = OUT / "policy.json"
    policy = json.loads(policy_file.read_text(encoding="utf-8"))
    picked = next((entry for entry in payload["policies"] if entry["name"] == chosen["policy"]), {})
    if chosen["adopted"]:
        policy["glide"].update({"mode": "dynamic", **{key: picked[key] for key in ("half_life_sessions", "prior_sessions", "score_floor", "blend_every", "max_generations")}})
        policy["glide_policy"] = chosen["policy"]
    policy_file.write_text(json.dumps(policy, indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    for name, row in sorted(results.items(), key=lambda item: item[1]["median_regret"]):
        print(f"{name:32s} regret {row['median_regret']:.3f}  zero-alpha time {row['zero_alpha_majority_share']:.3f}  holders {row['mean_holders']:.2f}  turnover/yr {row['turnover_per_year']:.2f}")
    print("chosen:", chosen["policy"], "| adopted:", chosen["adopted"], "|", chosen["reason"])
    return 0


def stage_decay() -> int:
    reports = {
        "1_to_0": average_run_lengths(expected_sharpe=1.0, decayed_sharpe=0.0, paths=500),
        "0.5_to_0": average_run_lengths(expected_sharpe=0.5, decayed_sharpe=0.0, paths=500),
        "0_to_-1": average_run_lengths(expected_sharpe=0.0, decayed_sharpe=-1.0, paths=500),
    }
    out = ROOT / "ml" / "evaluation" / "v661" / "decay_run_lengths.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(reports, indent=1), encoding="utf-8", newline="\n")
    print(json.dumps(reports, indent=1))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("stage", choices=["rules", "run", "decay", "rules2", "run2"])
    parser.add_argument("--paths", type=int, default=2000)
    parser.add_argument("--workers", type=int, default=1)
    args = parser.parse_args()
    return {
        "rules": stage_rules, "run": lambda: stage_run(args.paths), "decay": stage_decay, "rules2": stage_rules2, "run2": lambda: stage_run2(args.paths, args.workers),
    }[args.stage]()


if __name__ == "__main__":
    raise SystemExit(main())
