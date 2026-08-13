"""Evaluation-dashboard state for Aether Quant's webui (V5.1 Phase 0).

Reads the JSON reports `aq evaluate` writes (ml/evaluation/*.json) and
reshapes them into one payload for the /api/evaluation endpoint and the
webui's Evaluation tab. Pure, read-only - never runs a simulation itself
(that is `aq evaluate`'s job); this module only serves whatever `aq
evaluate` last wrote to disk.

Each section degrades independently to {"status": "not_evaluated"} when
its source file is missing - never raises, mirroring
monitoring/neural_network_state.py::build_neural_network_state()'s own
per-network degrade-gracefully contract. A user who has never run `aq
evaluate` sees an honest "not evaluated yet" tab, not a 404/500.
"""

from __future__ import annotations

import json
from pathlib import Path

DEFAULT_ML_DIR = Path(__file__).resolve().parent.parent / "ml"


def _load_json(path: Path) -> dict | list | None:
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def _not_evaluated(hint: str) -> dict:
    return {"status": "not_evaluated", "hint": hint}


def build_evaluation_state(ml_dir: Path | None = None) -> dict:
    """Reads ml/evaluation/{rank_book_simulation,capacity_report,
    cost_stress_report,ablation_report,book_spread_calibration,
    book_history_reconciliation,kill_switch_replay}.json plus the newest
    ml/versions/walk-forward-*/walk_forward_summary.json (Phase 4 - absent
    until that phase ships, degrades the same way). Every section is
    independently optional; a partial `aq evaluate` run (e.g. just
    --rank-book) still produces a fully-formed response with the
    unreported sections marked not_evaluated rather than omitted."""
    ml_dir = ml_dir or DEFAULT_ML_DIR
    evaluation_dir = ml_dir / "evaluation"

    rank_book = _load_json(evaluation_dir / "rank_book_simulation.json")
    capacity = _load_json(evaluation_dir / "capacity_report.json")
    stress_report = _load_json(evaluation_dir / "cost_stress_report.json")
    ablation = _load_json(evaluation_dir / "ablation_report.json")
    walk_forward = _latest_walk_forward_summary(ml_dir)
    # V5.1 report that was never wired in here until V5.2.3 - a pre-
    # existing gap, closed alongside book_history_reconciliation below
    # since this function already touches every other `aq evaluate`
    # report.
    book_spread_calibration = _load_json(evaluation_dir / "book_spread_calibration.json")
    # V5.2.2/V5.2.3 (development/Problems.md #91) - `aq evaluate
    # --reconcile-book-history`'s persisted payload (per-date diffs +
    # aggregate summary + universe_summary once V5.2.3's
    # include_full_universe toggle has been used for a run).
    book_history_reconciliation = _load_json(evaluation_dir / "book_history_reconciliation.json")
    # V5.2.8 (development/Problems.md #94) - `aq evaluate --replay-kill-switch`'s
    # persisted payload, never wired into this state builder until now -
    # same honest gap book_history_reconciliation had before V5.2.3.
    kill_switch_replay = _load_json(evaluation_dir / "kill_switch_replay.json")

    # Every section follows the same shape convention: the raw report dict
    # when present, or {"status": "not_evaluated", "hint": ...} when not -
    # "stress" is wrapped in {"entries": [...]} since its report is a bare
    # list (one entry per cost multiplier), which has no room for its own
    # "status"/"hint" keys.
    return {
        "rank_book": rank_book or _not_evaluated("run `aq evaluate --rank-book`"),
        "capacity": capacity or _not_evaluated("run `aq evaluate --capacity`"),
        "stress": (
            {"entries": stress_report["stress"]}
            if stress_report and "stress" in stress_report
            else _not_evaluated("run `aq evaluate --stress`")
        ),
        "ablation": ablation or _not_evaluated("run `aq evaluate --ablation`"),
        "walk_forward": walk_forward or _not_evaluated("run `aq train --walk-forward --include-multitask --include-sequence`"),
        "book_spread_calibration": book_spread_calibration or _not_evaluated("run `aq evaluate --calibrate-book-spread`"),
        "book_history_reconciliation": book_history_reconciliation
        or _not_evaluated("run `aq evaluate --reconcile-book-history` (needs a backtest with phase_v2.diagnostics.book_history.enabled=true first)"),
        "kill_switch_replay": kill_switch_replay or _not_evaluated("run `aq evaluate --replay-kill-switch`"),
    }


def _latest_walk_forward_summary(ml_dir: Path) -> dict | None:
    """The most recently modified ml/versions/walk-forward-*/walk_forward_summary.json,
    if any - `_run_walk_forward()` (train.py) writes one such directory per
    run, each with its own uuid-suffixed name, so "latest" is by file
    mtime, not by name sort order."""
    versions_dir = ml_dir / "versions"
    if not versions_dir.exists():
        return None

    candidates = sorted(
        versions_dir.glob("walk-forward-*/walk_forward_summary.json"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if not candidates:
        return None
    return _load_json(candidates[0])
