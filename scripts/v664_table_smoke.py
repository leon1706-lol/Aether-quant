"""Builds every trial's table of a round on its cell and reports coverage: names per rebalance and the first and last date with any value (V6.6.4).

This scores nothing and reads no return: it checks that a pre-registered trial can be built from the cell's data, so a defect shows before the rule file is hashed and not after. It runs on a
free cell only.

    python scripts/v664_table_smoke.py ml/evaluation/v664/round4c_draft.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402

from evaluation.research_cells import FREE_CELLS  # noqa: E402
from evaluation.research_round import RoundSpec, live_rows, trial_table  # noqa: E402
from evaluation.research_round import _load_selection_cell as load_cell  # noqa: E402
from portfolio.wide_signals import live_names_per_rebalance  # noqa: E402


def smoke(spec: RoundSpec, score_dir: Path, *, emit=print) -> dict:
    if spec.cell not in FREE_CELLS:
        raise PermissionError("the smoke test opens free cells only")
    cell = load_cell(spec, ROOT)
    built: dict[str, pd.DataFrame] = {}
    report: dict[str, dict] = {}
    for trial, entry in spec.trials.items():
        table = trial_table(spec, trial, cell, built, score_dir=score_dir)
        if table is None:
            report[trial] = {"built": False}
            emit(f"{trial}: not built (an input or a part is missing)")
            continue
        built[trial] = table
        start = str(entry.get("start") or cell.cell.start)
        live = live_names_per_rebalance(live_rows(table.loc[table.index >= start], entry), int(entry.get("rebalance_every", 20)))
        any_value = table.notna().any(axis=1)
        report[trial] = {
            "built": True, "median_live_names": live["median"], "min_live_names": live["minimum"], "first": str(any_value.idxmax()) if any_value.any() else None,
            "last": str(any_value[::-1].idxmax()) if any_value.any() else None,
        }
        emit(f"{trial}: live names median {live['median']:.0f} min {live['minimum']:.0f}, values from {report[trial]['first']} to {report[trial]['last']}")
    return report


def main() -> int:
    from evaluation.research_round import RoundSpec as Spec

    draft = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    spec = Spec(
        name=draft["name"], cell=draft["cell"], side=draft["side"], bar=draft["bar"], rule=draft["rule"], trials=draft["trials"], out_dir=ROOT / draft["out_dir"], ledger=ROOT / draft["ledger"],
        track=draft["track"], min_live_names=int(draft["min_live_names"]), min_ic_names=int(draft["min_ic_names"]), no_ic_clause=tuple(draft.get("no_ic_clause") or ()), raw=draft,
    )
    smoke(spec, spec.out_dir / "scores")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
