"""Every research variant ever scored by a pre-registered rule, as one trial list (V6.3.0) -> the deflated Sharpe ratio's
N and Sharpe variance (`evaluation/backtest_statistics.py`, README "Return/Risk Efficiency").

Each rule chain's `ml/evaluation/<phase>/research.json` stores, per variant and scoring mode, one summary per split with
`median_net_sharpe` over the rebalance phases. A trial is one (phase, stage, variant, mode) scored on the backtest split
(the split variants were selected on); a summary repeated verbatim (the base book re-scored in every stage) counts once.

    python scripts/build_trial_registry.py [--evaluation-dir ml/evaluation] [--out ml/evaluation/trial_registry.json]
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPLIT = "backtest"


def collect_trials(payload, phase: str, path: tuple[str, ...] = ()) -> list[dict]:
    """(phase, path, median Sharpe) for every `<...>/backtest/{median_net_sharpe}` summary in a research payload."""
    trials: list[dict] = []
    if isinstance(payload, dict):
        summary = payload.get(SPLIT)
        if isinstance(summary, dict) and isinstance(summary.get("median_net_sharpe"), (int, float)):
            value = float(summary["median_net_sharpe"])
            if math.isfinite(value):
                trials.append({
                    "phase": phase, "trial": "/".join(path), "split": SPLIT, "median_sharpe": value,
                    "phases": summary.get("phases"), "annualization": 252,
                })
        for key, child in payload.items():
            if key != SPLIT:
                trials.extend(collect_trials(child, phase, path + (str(key),)))
    elif isinstance(payload, list):
        for index, child in enumerate(payload):
            trials.extend(collect_trials(child, phase, path + (str(index),)))
    return trials


def dedupe(trials: list[dict]) -> list[dict]:
    """One trial per distinct (phase, score): the same configuration re-scored in a later stage is not a new trial."""
    seen: set[tuple[str, float]] = set()
    unique = []
    for trial in trials:
        key = (trial["phase"], round(trial["median_sharpe"], 9))
        if key in seen:
            continue
        seen.add(key)
        unique.append(trial)
    return unique


def build_registry(evaluation_dir: Path) -> dict:
    trials: list[dict] = []
    sources = []
    for research in sorted(Path(evaluation_dir).glob("v*/research.json")):
        try:
            payload = json.loads(research.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        sources.append(research.relative_to(evaluation_dir).as_posix())
        trials.extend(collect_trials(payload, research.parent.name))
    trials = dedupe(trials)
    return {"sources": sources, "num_trials": len(trials), "split": SPLIT, "trials": trials}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--evaluation-dir", type=Path, default=ROOT / "ml" / "evaluation")
    parser.add_argument("--out", type=Path, default=ROOT / "ml" / "evaluation" / "trial_registry.json")
    args = parser.parse_args()
    registry = build_registry(args.evaluation_dir)
    args.out.write_text(json.dumps(registry, indent=2), encoding="utf-8")
    print(f"{registry['num_trials']} trials from {', '.join(registry['sources']) or 'no research files'} -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
