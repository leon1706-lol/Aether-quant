"""scripts/ml_manifest.py: the installed-model manifest is stable, ignores non-models, and sees expert files."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from ml_manifest import manifest_lines  # noqa: E402


def test_manifest_lists_top_level_models_and_experts_only(tmp_path):
    (tmp_path / "multitask_model.json").write_text("{}", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("x", encoding="utf-8")
    (tmp_path / "datasets").mkdir()
    (tmp_path / "datasets" / "full_dataset.json").write_text("{}", encoding="utf-8")
    (tmp_path / "expert_models" / "bullish").mkdir(parents=True)
    (tmp_path / "expert_models" / "bullish" / "model.json").write_text("{}", encoding="utf-8")
    lines = manifest_lines(tmp_path)
    assert [line.split("  ", 1)[1] for line in lines] == ["expert_models/bullish/model.json", "multitask_model.json"]
    assert manifest_lines(tmp_path) == lines


def test_manifest_changes_when_a_model_changes(tmp_path):
    path = tmp_path / "multitask_model.json"
    path.write_text("{}", encoding="utf-8")
    before = manifest_lines(tmp_path)
    path.write_text('{"a": 1}', encoding="utf-8")
    assert manifest_lines(tmp_path) != before
