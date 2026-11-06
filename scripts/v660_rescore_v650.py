"""V6.5.0's sleeves rescored on what V6.6.0 found wrong with their Sharpes: excess returns, and sessions at 252 where a panel has no weekend rows.

Report only, on the V6.5.0 selection windows, with each sleeve's frozen spec. R-EDGE1 stays closed and nothing is reinstalled by this.

    python scripts/v660_rescore_v650.py [--only t3_trend_blend ...]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from v650_research import ALL_SPECS, load_context, read_json, window_of  # noqa: E402

from evaluation.premia_research import passes_sharpe_clauses, score_sleeve  # noqa: E402

V650 = ROOT / "ml" / "evaluation" / "v650"
OUT = ROOT / "ml" / "evaluation" / "v660" / "v650_rescore.json"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--only", nargs="*", default=None)
    args = parser.parse_args()
    rules = json.loads((V650 / "rules.json").read_text(encoding="utf-8"))
    frozen = read_json(V650 / "selection_scores.json", {})
    context = load_context()
    report = read_json(OUT, {})
    for spec in ALL_SPECS:
        if (args.only and spec.id not in args.only) or spec.id in report:
            continue
        table = spec.params.get("table")
        if table is not None and table not in context.panel.extras:
            continue
        start, split, end = window_of(spec, rules)
        score = score_sleeve(spec, context, start=start, split=split, end=end)
        score.pop("daily", None)
        old = frozen.get(spec.id) or {}
        report[spec.id] = {
            "frozen": {key: old.get(key) for key in ("sharpe", "sharpe_first_half", "sharpe_second_half")},
            "rescored": {key: score.get(key) for key in ("sharpe", "sharpe_first_half", "sharpe_second_half")},
            "frozen_passed_sharpe_clauses": passes_sharpe_clauses(old) if old else None,
            "rescored_passes_sharpe_clauses": passes_sharpe_clauses(score),
        }
        OUT.write_text(json.dumps(report, indent=1), encoding="utf-8", newline="\n")
        print(spec.id, report[spec.id]["frozen"]["sharpe"], "->", report[spec.id]["rescored"]["sharpe"], flush=True)
    changed = {name: row for name, row in report.items() if row["frozen_passed_sharpe_clauses"] != row["rescored_passes_sharpe_clauses"]}
    print(f"{len(report)} rescored, {len(changed)} changed their Sharpe clauses: {sorted(changed)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
