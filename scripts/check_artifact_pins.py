"""Fails (exit 1) when an installed model file differs from `ml/artifact_pins.json` (V6.6.9, Problems #382). `aq verify --quick` runs it.

    python scripts/check_artifact_pins.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from retraining.artifact_pins import artifact_problems  # noqa: E402


def main() -> int:
    if not (ROOT / "ml" / "sequence_model.json").exists():
        print("no installed models here (a clean checkout): nothing to check")
        return 0
    problems = artifact_problems(ROOT / "ml", ROOT / "ml" / "artifact_pins.json")
    for problem in problems:
        print(problem, file=sys.stderr)
    print("the installed models match their pins" if not problems else f"{len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
