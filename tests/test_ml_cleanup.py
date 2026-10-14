"""evaluation/ml_cleanup.py (V5.8.0): the `aq clean ml` plan protects what is in use and deletes nothing itself."""

from __future__ import annotations

import json
import os

from evaluation.ml_cleanup import active_version_ids, plan_ml_cleanup


def _dir(path, size=100, mtime=None):
    path.mkdir(parents=True)
    (path / "blob.bin").write_bytes(b"x" * size)
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return path


def test_plan_protects_active_newest_and_newest_backup(tmp_path):
    ml = tmp_path / "ml"
    ml.mkdir()
    (ml / "multitask_training_metrics.json").write_text(json.dumps({"version_id": "active_mt"}))
    (ml / "broken_training_metrics.json").write_text("{nope")
    _dir(ml / "versions" / "active_mt", 10, mtime=1)
    _dir(ml / "versions" / "old_a", 1000, mtime=2)
    _dir(ml / "versions" / "old_b", 2000, mtime=3)
    _dir(ml / "versions" / "newest", 5, mtime=100)
    _dir(ml / "_backup_old", 4000, mtime=5)
    _dir(ml / "_backup_new", 300, mtime=50)
    assert active_version_ids(ml) == {"active_mt"}

    plan = plan_ml_cleanup(ml, keep_versions=1, keep_backups=1)
    removed = {os.path.basename(item["path"]): item for item in plan["items"]}
    assert set(removed) == {"old_a", "old_b", "_backup_old"}
    assert plan["total_bytes"] == sum(item["bytes"] for item in plan["items"]) >= 7000
    assert (ml / "versions" / "old_a").exists()  # planning never deletes


def test_walk_forward_window_datasets_are_listed_only_on_request(tmp_path):
    ml = tmp_path / "ml"
    window = _dir(ml / "versions" / "walk-forward-1" / "window_0", 10, mtime=10)
    (window / "full_dataset.csv").write_bytes(b"y" * 500)
    (window / "window_result.json").write_text("{}")
    off = plan_ml_cleanup(ml, keep_versions=5)
    on = plan_ml_cleanup(ml, keep_versions=5, strip_walk_forward_datasets=True)
    assert off["items"] == []
    assert [os.path.basename(item["path"]) for item in on["items"]] == ["full_dataset.csv"]
