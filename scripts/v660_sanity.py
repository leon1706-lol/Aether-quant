"""Is the wide scoring path able to see an edge at all? A result of "no edge" is worthless if the path is broken, so before it's believed:

an oracle signal (the label itself, which reads the future) must score hugely, its reversal hugely badly, and a random signal about zero less costs.
These are plumbing: they enter no ledger, no PBO and no count of trials, and read only cell S.

    python scripts/v660_sanity.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from v660_trials import W  # noqa: E402

from evaluation.premia_research import score_sleeve  # noqa: E402
from evaluation.wide_context import equity_cell, signal_ic_t  # noqa: E402
from portfolio.premia_signals import SleeveSpec  # noqa: E402

OUT = ROOT / "ml" / "evaluation" / "v660" / "sanity_wide_path.json"


def main() -> int:
    base = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    cell = equity_cell(ROOT, base, "S", with_info=False)
    template = W[0]
    member = cell.member
    label = cell.label.where(member)
    rng = np.random.default_rng(66)
    random_table = pd.DataFrame(rng.normal(size=label.shape), index=label.index, columns=label.columns).where(member)
    tables = {"oracle": label, "reversed_oracle": -label, "random": random_table}
    report = {}
    for name, table in tables.items():
        cell.context.panel.extras[name] = table
        spec = SleeveSpec(name, "sanity", template.kind, template.family, template.universe, template.rebalance_every, {"table": name, "top_k": template.params["top_k"]})
        score = score_sleeve(spec, cell.context, start=cell.cell.start, split=cell.cell.split, end=cell.cell.end, signal=table)
        score.pop("daily")
        ic = signal_ic_t(table, cell.label, start=cell.cell.start, end=cell.cell.end)
        report[name] = {"sharpe": score["sharpe"], "first_half": score["sharpe_first_half"], "second_half": score["sharpe_second_half"], "mean_gross": score["mean_gross"], "turnover": score["turnover"], "mean_ic": ic["mean_ic"]}
        print(name, report[name], flush=True)
    OUT.write_text(json.dumps(report, indent=1), encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
