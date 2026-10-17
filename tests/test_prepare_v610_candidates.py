"""scripts/prepare_v610_candidates.py (V6.1.0): R-HEAD per candidate and the scoreable candidate directory."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys_path_added = str(ROOT / "scripts")
import sys  # noqa: E402

sys.path.insert(0, sys_path_added)
spec = importlib.util.spec_from_file_location("prepare_v610_candidates", ROOT / "scripts" / "prepare_v610_candidates.py")
prepare = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prepare)


def _member(tmp_path, name, status):
    directory = tmp_path / name
    directory.mkdir()
    metrics = {"backtest": {"rank_20d_ranking_quality": {"quality_status": status}}}
    (directory / "multitask_training_metrics.json").write_text(json.dumps(metrics), encoding="utf-8")
    return directory


def test_a_head_passes_when_half_the_members_pass_it(tmp_path):
    members = [_member(tmp_path, "a", "watchlist"), _member(tmp_path, "b", "not_promotable")]
    assert prepare.head_status(members, "multitask", "rank_20d")
    members.append(_member(tmp_path, "c", "not_promotable"))
    assert not prepare.head_status(members, "multitask", "rank_20d")
    assert not prepare.head_status([], "multitask", "rank_20d")
