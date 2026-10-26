"""Is every block of the README's Backtest Statistics current (V6.3.0, the end-of-phase recapture check)?

Each `AQ:*` block between "## Backtest Statistics" and "## Test Suite" is dated by the timestamp it prints ("computed ...",
"Last updated | ...") or, when it prints none, by the newest mtime of the files it is rendered from. A block is stale when
that date is before `--since`, unless it is named with `--allow`. The walk-forward blocks are model-bound: they describe the
installed models, so they are stale only when dated before those models were written (a retrain refreshes them, nothing
else can). Lean-reading blocks must name the pinned run (`ml/evaluation/readme_lean_run.json`).

    python scripts/readme_freshness.py --since 2026-10-18 [--allow BLOCK ...]
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVALUATION = ROOT / "ml" / "evaluation"
BLOCK_RE = re.compile(r"<!-- AQ:([A-Z0-9_]+)_START -->(.*?)<!-- AQ:\1_END -->", re.DOTALL)
STAMP_RE = re.compile(r"(?:computed|Last updated \|)\s+(\d{4}-\d{2}-\d{2})")
RUN_RE = re.compile(r"`?(\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2})`?")
# blocks that print no timestamp: the files they are rendered from
SOURCES = {
    "ASLIVE": ["rank_book_simulation_as_live_validation.json", "rank_book_simulation_as_live_backtest.json"],
    "LEANCMP": ["backtest_audit.json"],
    "RESEARCH": ["v630/research.json", "v630/calibration.json", "head_audit.json", "holdout_report.json",
                 "v640/research.json", "v640/r_lean13.json", "v642/r_lean14_bt7.json", "v642/r_lean14_bt8.json"],
    "BACKTEST_HISTORY": [],
    "MONTECARLO_FULL_STATS": ["monte_carlo.json"],
    "EVAL_FULL_STATS": ["rank_book_simulation_sequence.json", "rank_book_simulation_multitask.json"],
    "WALKFORWARD_FULL_STATS": [],
}
LEAN_BLOCKS = ("BACKTEST_HISTORY", "BTSTATS_GENERAL", "BTSTATS_PERFORMANCE", "BTSTATS_RUNS", "BTSTATS_SHORTFALL",
               "BTSTATS_EFFICIENCY", "BTSTATS_CLASSIFICATION", "BTSTATS_ATTRIBUTION")
MODEL_BOUND = ("WALKFORWARD", "WALKFORWARD_FULL_STATS")
# the installed models the model-bound blocks describe (ml/, written by a retrain)
MODEL_FILES = ("model_weights.json", "multitask_model.json", "sequence_model.json")


def models_written(ml_dir: Path = ROOT / "ml") -> str | None:
    """UTC date the newest installed model artifact was written, None when none exists."""
    stamps = [(ml_dir / name).stat().st_mtime for name in MODEL_FILES if (ml_dir / name).exists()]
    return datetime.fromtimestamp(max(stamps), tz=timezone.utc).date().isoformat() if stamps else None


def section(text: str) -> str:
    start = text.find("## Backtest Statistics")
    end = text.find("## Test Suite", start)
    return text[start:end] if start >= 0 else ""


def block_dates(text: str, evaluation_dir: Path = EVALUATION) -> dict[str, dict]:
    """{block: {"date": newest date or None, "source": "printed" | "files" | "none", "runs": runs named}}."""
    out = {}
    for name, body in BLOCK_RE.findall(section(text)):
        printed = STAMP_RE.findall(body)
        if printed:
            out[name] = {"date": max(printed), "source": "printed", "runs": sorted(set(RUN_RE.findall(body)))}
            continue
        mtimes = [
            datetime.fromtimestamp((evaluation_dir / rel).stat().st_mtime, tz=timezone.utc).date().isoformat()
            for rel in SOURCES.get(name, []) if (evaluation_dir / rel).exists()
        ]
        out[name] = {"date": max(mtimes) if mtimes else None, "source": "files" if mtimes else "none",
                     "runs": sorted(set(RUN_RE.findall(body)))}
    return out


def stale_blocks(dates: dict[str, dict], since: str, allow: set[str], pinned_run: str | None,
                 models_date: str | None = None) -> list[str]:
    problems = []
    for name, info in sorted(dates.items()):
        if name in allow:
            continue
        bound = models_date if name in MODEL_BOUND and models_date else since
        if info["date"] is None or info["date"] < bound:
            what = f"the installed models ({bound})" if bound != since else since
            problems.append(f"{name}: dated {info['date'] or 'nowhere'} ({info['source']}), before {what}")
        if pinned_run and name in LEAN_BLOCKS and pinned_run not in info["runs"]:
            problems.append(f"{name}: does not name the pinned run {pinned_run}")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--since", required=True, help="ISO date: every block must be dated on or after it")
    parser.add_argument("--allow", action="append", default=[], help="a block name exempt from the date check")
    parser.add_argument("--readme", type=Path, default=ROOT / "README.md")
    args = parser.parse_args()
    dates = block_dates(args.readme.read_text(encoding="utf-8"))
    pin = EVALUATION / "readme_lean_run.json"
    pinned = json.loads(pin.read_text(encoding="utf-8")).get("run") if pin.exists() else None
    for name, info in sorted(dates.items()):
        print(f"{name:28s} {info['date'] or '-':10s} {info['source']:8s} {', '.join(info['runs'][:2])}")
    problems = stale_blocks(dates, args.since, set(args.allow), pinned, models_written())
    for problem in problems:
        print("STALE:", problem)
    print(f"{len(dates)} blocks, {len(problems)} problem(s); pinned run {pinned or 'none'}")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
