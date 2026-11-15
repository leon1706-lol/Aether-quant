"""evaluation/wide_context.py (V6.6.7: its own test file, the convention in tests/README.md; the deeper cases live in the round files)."""

from __future__ import annotations

from evaluation.wide_context import path_config
from portfolio.target_weights import TargetWeightsConfig


def test_the_research_path_config_is_a_target_weights_config():
    import json
    from pathlib import Path

    config = json.loads((Path(__file__).resolve().parents[1] / "config.json").read_text(encoding="utf-8"))
    assert isinstance(path_config(config), TargetWeightsConfig)
