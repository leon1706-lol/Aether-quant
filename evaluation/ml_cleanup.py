"""Disk plan for `ml/` (V5.8.0, `aq clean ml`).

`ml/` had grown to 15 GB on a 4 GB-RAM / small-disk PC: `ml/versions` 8.9 GB of per-candidate trees (each walk-forward
window carries a regenerable ~2.2 GB `full_dataset.csv`), `ml/_backup_*` another ~4 GB. This module only PLANS: it lists
what could go and why, protecting the models in use, and the CLI deletes nothing without `--apply`.

Protected, always: every version id named by a `version_id` field of the active `ml/*_training_metrics.json` files, the
newest `keep_versions` version directories by modification time, the newest `keep_backups` backup directories, and the
active top-level files. Pure stdlib; sizes are summed with `os.scandir` (no file is opened).
"""

from __future__ import annotations

import json
import os
from pathlib import Path


def directory_size(path: Path) -> int:
    total = 0
    stack = [str(path)]
    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    if entry.is_dir(follow_symlinks=False):
                        stack.append(entry.path)
                    else:
                        try:
                            total += entry.stat(follow_symlinks=False).st_size
                        except OSError:
                            continue
        except OSError:
            continue
    return total


def active_version_ids(ml_dir: Path) -> set[str]:
    """Version ids the active metrics files point at (the lineage of the installed models)."""
    found: set[str] = set()
    for path in Path(ml_dir).glob("*training_metrics.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(payload, dict) and payload.get("version_id"):
            found.add(str(payload["version_id"]))
    return found


def plan_ml_cleanup(
    ml_dir: Path, *, keep_versions: int = 5, keep_backups: int = 1, strip_walk_forward_datasets: bool = False
) -> dict:
    """{"items": [{"path", "bytes", "kind", "reason"}], "total_bytes", "protected": [...]} - nothing is deleted."""
    ml_dir = Path(ml_dir)
    protected_ids = active_version_ids(ml_dir)
    items: list[dict] = []
    protected: list[str] = []

    versions_dir = ml_dir / "versions"
    if versions_dir.is_dir():
        version_dirs = sorted((d for d in versions_dir.iterdir() if d.is_dir()), key=lambda d: d.stat().st_mtime, reverse=True)
        newest = {d.name for d in version_dirs[: max(0, keep_versions)]}
        for directory in version_dirs:
            if directory.name in protected_ids or directory.name in newest:
                protected.append(str(directory))
                if strip_walk_forward_datasets and directory.name.startswith("walk-forward-"):
                    items.extend(_walk_forward_dataset_items(directory))
                continue
            items.append({"path": str(directory), "bytes": directory_size(directory), "kind": "version",
                          "reason": "not referenced by an active metrics file and not among the newest versions"})
    backups = sorted((d for d in ml_dir.glob("_backup_*") if d.is_dir()), key=lambda d: d.stat().st_mtime, reverse=True)
    for index, directory in enumerate(backups):
        if index < max(0, keep_backups):
            protected.append(str(directory))
            continue
        items.append({"path": str(directory), "bytes": directory_size(directory), "kind": "backup", "reason": "older backup"})
    return {"items": items, "total_bytes": sum(item["bytes"] for item in items), "protected": protected,
            "active_version_ids": sorted(protected_ids)}


def _walk_forward_dataset_items(directory: Path) -> list[dict]:
    items = []
    for window in sorted(directory.glob("window_*")):
        for name in ("full_dataset.csv", "train_dataset.csv", "validation_dataset.csv", "backtest_dataset.csv"):
            path = window / name
            if path.is_file():
                items.append({"path": str(path), "bytes": path.stat().st_size, "kind": "walk_forward_dataset",
                              "reason": "regenerable window dataset (models, metrics and summary are kept)"})
    return items
