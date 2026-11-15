"""data_pipeline/v2_manifest.py (V6.6.7: its own test file, the convention in tests/README.md; the deeper cases live in the round files)."""

from __future__ import annotations

from data_pipeline.v2_manifest import build_v2_pipeline_manifest


def test_a_manifest_is_built_from_the_project_config():
    import json
    from pathlib import Path

    config = json.loads((Path(__file__).resolve().parents[1] / "config.json").read_text(encoding="utf-8"))
    manifest = build_v2_pipeline_manifest(config)
    assert isinstance(manifest, dict) and manifest
