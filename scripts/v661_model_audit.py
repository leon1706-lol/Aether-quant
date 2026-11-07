"""V6.6.1's audit of what the models could know, on free cell S: 18 fixed group x horizon looks, each counted in the trial ledger.

    python scripts/v661_model_audit.py [--out ml/evaluation/v661/model_audit.json]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from evaluation.model_audit import FEATURE_GROUPS, HORIZONS, feature_group_ic, fundamental_coverage  # noqa: E402
from evaluation.trial_ledger import append_trial, read_ledger  # noqa: E402
from evaluation.wide_context import equity_cell  # noqa: E402

LEDGER = ROOT / "ml" / "evaluation" / "v660" / "trial_ledger.jsonl"


def count_looks(path: Path) -> list[str]:
    """Appends each look once, with no Sharpe: it raises N and leaves the variance unchanged."""
    held = {entry["trial_id"] for entry in read_ledger(path)}
    added = []
    for group in FEATURE_GROUPS:
        for horizon in HORIZONS:
            trial = f"audit:{group}:{horizon}"
            if trial not in held:
                append_trial(path, trial_id=trial, track="A", window="v660_selection", role="candidate", annualised_sharpe=None, n_obs=0, engine="offline", detail={"cell": "S", "round": "round3_audit"})
                added.append(trial)
    return added


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", default=str(ROOT / "ml" / "evaluation" / "v661" / "model_audit.json"))
    args = parser.parse_args(argv)
    base = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    cell = equity_cell(ROOT, base, "S")
    report = {"cell": "S", "coverage": fundamental_coverage(cell.features, cell.member), "groups": feature_group_ic(cell), "looks_added": count_looks(LEDGER)}
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=1, default=str), encoding="utf-8", newline="\n")
    for group, by_horizon in report["groups"].items():
        print(group, {horizon: None if entry is None else (round(entry["mean_ic"] or 0.0, 4), round(entry["nonoverlap_t"] or 0.0, 2)) for horizon, entry in by_horizon.items()}, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
