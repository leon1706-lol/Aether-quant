"""A host's decision for a generation that can't decide on a bare runner: one that needs fundamentals, a model or a private contact (V6.6.1).

Appends one hashed row dated with the session the decision belongs to, to `forward/decisions.jsonl` on the `forward-ledger` branch. `scripts/cycle_daily.py` marks it. Push the branch before the next
open: the commit date is what shows the decision came first. The agent never pushes it; the host's scheduled job or its owner does.

    python scripts/cycle_decide.py --generation g0002 --weights <csv: ticker,weight> --ledger <worktree>/forward/decisions.jsonl --session 2026-11-06
"""

from __future__ import annotations

import argparse
import csv
import datetime
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from evaluation.forward_ledger import definition_sha256, read_ledger  # noqa: E402
from evaluation.generation_ledger import append_event  # noqa: E402
from evaluation.generation_registry import load_registry  # noqa: E402

DECISION_EVENT = "generation_decision"


def read_weights(path: Path) -> dict[str, float]:
    """Raises on a non-finite weight: a damaged decision must not reach the record."""
    weights: dict[str, float] = {}
    with Path(path).open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            value = float(row["weight"])
            if not math.isfinite(value):
                raise ValueError(f"non-finite weight for {row['ticker']}")
            weights[row["ticker"]] = value
    return weights


def write_decision(registry: Path, generation: str, weights: dict[str, float], ledger: Path, *, session: str, created_at: str, source: str = "") -> dict | None:
    """Appends the decision, or None if this session already has one: a decision is made once."""
    generations = load_registry(registry)
    if generation not in generations:
        raise KeyError(f"{generation} is not in the registry")
    entry = generations[generation]
    if not entry.needs:
        raise ValueError(f"{generation} decides on the runner: a host's decision would be a second record")
    if any(row["payload"].get("candidate") == generation and row["payload"].get("session") == session for row in read_ledger(ledger)):
        return None
    payload = {"decided": weights, "definition_sha256": definition_sha256(entry.definition), "procedure_sha256": entry.procedure_sha256, "vintage": entry.vintages[-1] if entry.vintages else None, "source": source}
    return append_event(ledger, event=DECISION_EVENT, session=session, candidate=generation, payload=payload, created_at=created_at)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--registry", default=str(ROOT / "ml" / "generations" / "registry.json"))
    parser.add_argument("--generation", required=True)
    parser.add_argument("--weights", required=True)
    parser.add_argument("--ledger", required=True)
    parser.add_argument("--session", required=True)
    args = parser.parse_args(argv)
    created_at = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat()
    row = write_decision(Path(args.registry), args.generation, read_weights(Path(args.weights)), Path(args.ledger), session=args.session, created_at=created_at, source=args.weights)
    print("already decided" if row is None else f"{args.session} {args.generation}: {len(row['payload']['decided'])} weights")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
