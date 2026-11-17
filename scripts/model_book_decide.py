"""The model book's decision for one session (V6.6.9): the frozen candidate's holding after that session's close, as `ticker,weight`.

The book is generation g0006 (`ml/generations/registry.json`, `needs: "model"`): the runner has no models, so a host that has them decides and
pushes the decision. It refuses on a model file that differs from its pin, on closes that stopped updating and on scores older than a week.

    python scripts/v669_book.py scores --through 2026-11-13     # the installed models' scores up to the session (needs a refreshed dataset)
    python scripts/model_book_decide.py --session 2026-11-13 --out ml/cycle/g0006_2026-11-13.csv [--ledger <worktree>/forward/decisions.jsonl --generation g0006]

The data refresh that comes first is in `todo.md` "PC notes": `scripts/data_append_refresh.py`, then `scripts/splice_holdout_dataset.py`.
`--ledger` appends the dated decision (`scripts/cycle_decide.py`); pushing `forward/decisions.jsonl` to the `forward-ledger` branch is the owner's step.
"""

from __future__ import annotations

import argparse
import datetime
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from evaluation import model_book_round as rnd  # noqa: E402
from retraining.artifact_pins import artifact_problems  # noqa: E402

OUT = ROOT / "ml" / "evaluation" / "v669"


def long_sources() -> dict[str, Path]:
    return {name: OUT / "scores" / f"long_{name[-2:]}.csv" for name in ("ml_a1", "ml_a2", "ml_a3")}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--session", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--ledger", default=None)
    parser.add_argument("--generation", default=None)
    args = parser.parse_args(argv)
    problems = artifact_problems(ROOT / "ml", ROOT / "ml" / "artifact_pins.json")
    if problems:
        print(f"the model files are not the pinned ones: {problems}", file=sys.stderr)
        return 1
    from daily_target_weights import data_problems

    context = rnd.load_round_context(ROOT, long_sources())
    problems = [*data_problems(context, args.session), *filter(None, [rnd.score_problem(context, args.session)])]
    if problems:
        print("; ".join(problems), file=sys.stderr)
        return 1
    row = rnd.decide_row(context, rnd.check_freeze(OUT), args.session, rnd.read_json(OUT / "verification.json"))
    if row is None:
        print(f"{args.session} is before the book's first decision", file=sys.stderr)
        return 1
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    pd.Series(row, name="weight").rename_axis("ticker").reset_index().to_csv(out, index=False, lineterminator="\n")
    print(f"{args.session}: {len(row)} weights -> {out}")
    if args.ledger:
        if not args.generation:
            print("--ledger needs --generation", file=sys.stderr)
            return 2
        from cycle_decide import read_weights, write_decision

        created = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat()
        appended = write_decision(ROOT / "ml" / "generations" / "registry.json", args.generation, read_weights(out), Path(args.ledger), session=args.session, created_at=created, source=str(out))
        print("already decided" if appended is None else "decision appended; push forward/decisions.jsonl to the forward-ledger branch before the next 22:45 UTC run")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
