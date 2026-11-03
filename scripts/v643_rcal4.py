"""R-CAL4 (V6.4.3, rule in ml/evaluation/v643/r_cal4_rule.json): score one candidate simulator option against the BT5 / BT7 / BT8
Lean runs and decide it by the rule. The candidate is chosen from BT5's ladder (`scripts/lean_calibration.py`): there the
`live_gates` rung (live's resize threshold, entry cooldown and trailing stop replicas) lowers the daily correlation, so
C1 = the calibrated rung without those replicas (next-open fills, the fee floor, learned-topology sizing).

    python scripts/v643_rcal4.py [--calibration ml/evaluation/v643/calibration.json] [--out ml/evaluation/v643/r_cal4_result.json]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))
sys.path.insert(0, str(ROOT_DIR / "scripts"))

WINDOWS = {
    "bt5": "bt5=backtests/2026-10-22_10-56-13@2023-07-01..2026-10-16:backtest+holdout",
    "bt7": "bt7=backtests/2026-10-24_05-28-07@2023-07-01..2026-10-16:backtest+holdout",
    "bt8": "bt8=backtests/2026-10-24_18-50-22@2023-07-01..2026-10-16:backtest+holdout",
}
CANDIDATE = "c1_no_live_gates"
CANDIDATE_RUNG = {CANDIDATE: {"base": "min_fee", "topology": "mid"}}
MIN_GAIN = 0.05
BRANCH_A = 0.9


def verdict(base: dict, cand: dict) -> dict:
    """R-CAL4's clauses: chosen on BT5 (gain >= +0.05 there), BT7 and BT8 not lower."""
    gains = {name: (cand[name] - base[name]) if cand.get(name) is not None and base.get(name) is not None else None for name in base}
    checks = {
        "bt5_gain_ge_0.05": gains["bt5"] is not None and gains["bt5"] >= MIN_GAIN,
        "bt7_not_lower": gains["bt7"] is not None and gains["bt7"] >= 0.0,
        "bt8_not_lower": gains["bt8"] is not None and gains["bt8"] >= 0.0,
    }
    adopted = all(checks.values())
    best = cand if adopted else base
    return {"candidate": CANDIDATE, "base_correlation": base, "candidate_correlation": cand, "gains": gains, "checks": checks,
            "adopted": adopted, "branch": "A" if all(value is not None and value >= BRANCH_A for value in best.values()) else "B"}


def main() -> int:
    from lean_calibration import BOOK_COMPONENTS, parse_window, run_window

    from evaluation.sim_lean_calibration import gap_report

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--calibration", default=str(ROOT_DIR / "ml" / "evaluation" / "v643" / "calibration.json"))
    parser.add_argument("--dataset", default=str(ROOT_DIR / "ml" / "datasets" / "full_dataset.csv"))
    parser.add_argument("--out", default=str(ROOT_DIR / "ml" / "evaluation" / "v643" / "r_cal4_result.json"))
    args = parser.parse_args()
    calibration = json.loads(Path(args.calibration).read_text(encoding="utf-8"))
    config = json.loads((ROOT_DIR / "config.json").read_text(encoding="utf-8"))
    base, cand, rows = {}, {}, {}
    for name, text in WINDOWS.items():
        base[name] = calibration["windows"][name]["variants"]["calibrated"]["daily_correlation"]
        report = run_window(parse_window(text), Path(args.dataset), config, BOOK_COMPONENTS, extra_ladder=CANDIDATE_RUNG)
        rows[name] = report["variants"][CANDIDATE]
        cand[name] = rows[name].get("daily_correlation")
    result = verdict(base, cand)
    result["candidate_rows"] = {name: {key: value for key, value in row.items() if key != "disagreement"} for name, row in rows.items()}
    result["gap_report"] = gap_report(calibration)
    Path(args.out).write_text(json.dumps(result, indent=1, default=str), encoding="utf-8")
    print("R-CAL4:", json.dumps({key: result[key] for key in ("gains", "checks", "adopted", "branch")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
