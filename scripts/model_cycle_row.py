"""The weekly model cycle's record (V6.6.10, `.github/workflows/model-cycle.yml`): one JSON row per run, appended to a ledger file.

    python scripts/model_cycle_row.py --run-dir runs/<id> --examples example-models --ledger ../ledger/forward/model_cycle.jsonl

A row holds the date, the pipeline's gate verdicts, and each example model's zip hash and size (so a change in what the release
would publish is visible week by week). It never reads the project's own models: a free runner has none.
"""

from __future__ import annotations

import argparse
import datetime
import json
from pathlib import Path


def cycle_row(run_dir: Path, examples: Path, *, session: str) -> dict:
    report = json.loads((run_dir / "report.json").read_text(encoding="utf-8"))
    manifest_path = examples / "example_models_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {"models": {}}
    return {
        "session": session, "pipeline": report.get("name"), "gate": report.get("gate", {}),
        "examples": {name: {"sha256": entry["sha256"], "size": entry["size"]} for name, entry in sorted(manifest.get("models", {}).items())},
    }


def append_row(ledger: Path, row: dict) -> bool:
    """Appends `row` unless the ledger already holds a row for its session (a rerun the same day adds nothing). True when appended."""
    ledger.parent.mkdir(parents=True, exist_ok=True)
    existing = ledger.read_text(encoding="utf-8").splitlines() if ledger.exists() else []
    if any(json.loads(line).get("session") == row["session"] for line in existing if line.strip()):
        return False
    with ledger.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(row, sort_keys=True) + "\n")
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--examples", required=True)
    parser.add_argument("--ledger", required=True)
    parser.add_argument("--session", default=None, help="default: today, UTC")
    args = parser.parse_args(argv)
    session = args.session or datetime.datetime.now(datetime.timezone.utc).date().isoformat()
    row = cycle_row(Path(args.run_dir), Path(args.examples), session=session)
    print(("appended " if append_row(Path(args.ledger), row) else "already recorded ") + json.dumps(row))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
