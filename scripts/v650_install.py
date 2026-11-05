"""Installs the R-LEAN19 winner (V6.5.0): config.json becomes the frozen median-phase run's config, without its window override, and the
weight file moves next to the models. Refuses anything but the verdict's winner.

    python scripts/v650_install.py
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
V650 = ROOT / "ml" / "evaluation" / "v650"
INSTALLED_WEIGHTS = "ml/target_weights.csv"
INSTALLED_CANDIDATE = "ml/target_weights_candidate.json"
HISTORY_START = "2023-07-01"


def median_phase(phases: dict[str, dict]) -> str:
    """The phase with the median ex-T-bill Sharpe of an odd number of phases."""
    ordered = sorted(phases, key=lambda phase: phases[phase]["strategy_sharpe"])
    return ordered[len(ordered) // 2]


def main() -> int:
    verdict = json.loads((V650 / "r_lean19.json").read_text(encoding="utf-8"))
    winner = verdict["verdict"]["install"]
    if winner is None:
        print("R-LEAN19 installs nothing", file=sys.stderr)
        return 1
    phases = verdict["detail"][winner]["phases"]
    phase = median_phase(phases)
    run = phases[phase]["run"]
    config = json.loads((ROOT / "ml" / "evaluation" / "run_configs" / f"{run}.json").read_text(encoding="utf-8"))
    target = config["phase_v2"]["target_weights"]
    source = ROOT / target["weights_path"]
    if hashlib.sha256(source.read_bytes()).hexdigest() != target["weights_sha256"]:
        print(f"{source} is not the file the run froze", file=sys.stderr)
        return 1
    shutil.copyfile(source, ROOT / INSTALLED_WEIGHTS)
    target["weights_path"] = INSTALLED_WEIGHTS
    config["runtime"]["lean_window_override"] = None
    (ROOT / "config.json").write_text(json.dumps(config, indent=4), encoding="utf-8", newline="\n")
    candidate = {"survivors": [winner], "method": None, "phase_index": int(phase[1:]), "history_start": HISTORY_START, "pinned_run": run}
    (ROOT / INSTALLED_CANDIDATE).write_text(json.dumps(candidate, indent=1), encoding="utf-8", newline="\n")
    digest = hashlib.sha256((ROOT / "config.json").read_bytes()).hexdigest()
    print(json.dumps({"winner": winner, "phase": phase, "run": run, "config_sha256": digest, "weights_sha256": target["weights_sha256"]}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
