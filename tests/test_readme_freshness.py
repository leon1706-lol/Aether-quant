"""Tests for scripts/readme_freshness.py (V6.3.0): blocks are dated by their printed stamp or their source files, a block
before the cut-off is stale unless allowed, and Lean-reading blocks must name the pinned run."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load():
    spec = importlib.util.spec_from_file_location("_readme_freshness", ROOT / "scripts" / "readme_freshness.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


README = """# x
## Backtest Statistics
<!-- AQ:BTSTATS_GENERAL_START -->
| a | b |
_Run `2026-10-17_21-39-55` · computed 2026-10-18 10:53 UTC_
<!-- AQ:BTSTATS_GENERAL_END -->
<!-- AQ:EVAL_START -->
_Data computed 2026-10-16 16:46 UTC (rendered 2026-10-18 09:00 UTC)_
<!-- AQ:EVAL_END -->
<!-- AQ:WALKFORWARD_START -->
Last updated 2026-10-01
<!-- AQ:WALKFORWARD_END -->
<!-- AQ:ASLIVE_START -->
no stamp
<!-- AQ:ASLIVE_END -->
## Test Suite
<!-- AQ:TEST_COUNT_START -->1<!-- AQ:TEST_COUNT_END -->
"""


def test_blocks_are_dated_by_stamp_and_only_inside_the_section(tmp_path):
    freshness = _load()
    dates = freshness.block_dates(README, tmp_path)
    assert set(dates) == {"BTSTATS_GENERAL", "EVAL", "WALKFORWARD", "ASLIVE"}
    assert dates["BTSTATS_GENERAL"] == {"date": "2026-10-18", "source": "printed", "runs": ["2026-10-17_21-39-55"]}
    assert dates["EVAL"]["date"] == "2026-10-16"  # the computed date, not the rendered one
    assert dates["ASLIVE"]["source"] == "none"


def test_stale_and_pinned_checks(tmp_path):
    freshness = _load()
    dates = freshness.block_dates(README, tmp_path)
    problems = freshness.stale_blocks(dates, "2026-10-18", {"WALKFORWARD"}, "2026-10-17_21-39-55")
    assert any(problem.startswith("EVAL:") for problem in problems)
    assert any(problem.startswith("ASLIVE:") for problem in problems)
    assert not any(problem.startswith(("WALKFORWARD", "BTSTATS_GENERAL")) for problem in problems)
    other_pin = freshness.stale_blocks(dates, "2026-10-01", {"WALKFORWARD", "EVAL", "ASLIVE"}, "2026-11-01_00-00-00")
    assert other_pin == ["BTSTATS_GENERAL: does not name the pinned run 2026-11-01_00-00-00"]


def test_walk_forward_blocks_are_bound_to_the_installed_models(tmp_path):
    """V6.4.2: a walk-forward block describes the installed models, so it is current while it is newer than they are."""
    freshness = _load()
    readme = README.replace("Last updated 2026-10-01", "run `walk-forward-x`, computed 2026-10-01 11:53 UTC (rendered 2026-10-22 17:04 UTC)")
    dates = freshness.block_dates(readme, tmp_path)
    assert dates["WALKFORWARD"]["date"] == "2026-10-01"
    older_models = freshness.stale_blocks(dates, "2026-10-18", {"EVAL", "ASLIVE"}, None, models_date="2026-09-30")
    assert older_models == []
    newer_models = freshness.stale_blocks(dates, "2026-10-18", {"EVAL", "ASLIVE"}, None, models_date="2026-10-12")
    assert newer_models == ["WALKFORWARD: dated 2026-10-01 (printed), before the installed models (2026-10-12)"]
    no_models = freshness.stale_blocks(dates, "2026-10-18", {"EVAL", "ASLIVE"}, None)
    assert no_models and no_models[0].startswith("WALKFORWARD:")


def test_models_written_is_the_newest_model_artifact(tmp_path):
    import os

    freshness = _load()
    assert freshness.models_written(tmp_path) is None
    for name, stamp in (("model_weights.json", 1_760_000_000), ("multitask_model.json", 1_760_300_000)):
        (tmp_path / name).write_text("{}", encoding="utf-8")
        os.utime(tmp_path / name, (stamp, stamp))
    assert freshness.models_written(tmp_path) == "2025-10-12"
