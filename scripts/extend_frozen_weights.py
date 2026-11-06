"""Extends a copy of a frozen weight file by its frozen rule, for the forward check (RUNBOOK "Forward check").

The pinned file ends at its last decision before the data freeze. Rerunning it on newer prices measures old weights, not the
signal on new prices, so a forward rerun needs the rows the same rule would have written. The original is never touched: this
writes a copy and prints its sha256, for that run's config.

    python scripts/extend_frozen_weights.py --definition ml/evaluation/v650/installed_candidate.json \\
        --source ml/target_weights.csv --out ml/evaluation/v660/weights/forward.csv --end 2027-01-29
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))


def extended_rows(source: dict[str, dict[str, float]], new_rows: dict[str, dict[str, float]], last_frozen: str) -> dict[str, dict[str, float]]:
    """The frozen rows as they are, then every new row after them. A frozen row is never rewritten: that would change history."""
    return {**source, **{date: row for date, row in new_rows.items() if date > last_frozen}}


def main(argv: list[str] | None = None) -> int:
    from v650_lean import candidate_rows
    from v650_research import load_context

    from portfolio.target_weights import load_weight_file, write_weight_file

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--definition", required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--end", required=True)
    args = parser.parse_args(argv)
    if Path(args.out).resolve() == Path(args.source).resolve():
        parser.error("--out must be a copy, never the frozen file")
    definition = json.loads(Path(args.definition).read_text(encoding="utf-8"))
    source = load_weight_file(args.source)
    last_frozen = max(source)
    context = load_context()
    new_rows = candidate_rows(
        definition, context, start=str(definition.get("history_start", "2014-12-01")), end=args.end,
        phase_index=int(definition.get("phase_index", 0)),
    )
    rows = extended_rows(source, new_rows, last_frozen)
    digest = write_weight_file(rows, args.out)
    print(json.dumps({"last_frozen": last_frozen, "last_row": max(rows), "added": len(rows) - len(source), "sha256": digest}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
