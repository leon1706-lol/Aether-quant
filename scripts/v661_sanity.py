"""Can the pooled book see an edge at all? An oracle must score hugely, its reversal hugely badly, a random signal about zero less costs. Plumbing: these enter no
ledger, no PBO and no count of trials, and read only cell S.

    python scripts/v661_sanity.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from evaluation.premia_research import score_sleeve  # noqa: E402
from evaluation.wide_context import SECTORS, equity_cell, signal_ic_t  # noqa: E402
from portfolio.premia_signals import POOLED, SleeveSpec  # noqa: E402

OUT = ROOT / "ml" / "evaluation" / "v661" / "sanity_pooled.json"


def main() -> int:
    base = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    cell = equity_cell(ROOT, base, "S", with_info=False)
    label = cell.label.where(cell.member)
    rng = np.random.default_rng(661)
    random_table = pd.DataFrame(rng.normal(size=label.shape), index=label.index, columns=label.columns).where(cell.member)
    report = {}
    for name, table in {"oracle": label, "reversed_oracle": -label, "random": random_table}.items():
        cell.context.panel.extras[name] = table
        spec = SleeveSpec(name, "sanity", POOLED, "external_score", SECTORS, 20, {"table": name})
        score = score_sleeve(spec, cell.context, start=cell.cell.start, split=cell.cell.split, end=cell.cell.end, signal=table)
        score.pop("daily")
        ic = signal_ic_t(table, cell.label, start=cell.cell.start, end=cell.cell.end)
        report[name] = {"sharpe": score["sharpe"], "first_half": score["sharpe_first_half"], "second_half": score["sharpe_second_half"], "mean_gross": score["mean_gross"], "turnover": score["turnover"], "mean_ic": ic["mean_ic"]}
        print(name, report[name], flush=True)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=1), encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
