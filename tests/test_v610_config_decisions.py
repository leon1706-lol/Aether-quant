"""V6.1.0 config decisions, each pinned with the rule that made it (development/Changelog.md "V6.1.0")."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
V2 = CONFIG["phase_v2"]


def test_no_preset_carries_a_spread_gate_other_than_the_shipped_one():
    shipped = V2["portfolio_book"]["min_rank_confidence_spread"]
    for name, preset in V2["presets"].items():
        if isinstance(preset, dict):
            assert preset.get("phase_v2.portfolio_book.min_rank_confidence_spread", shipped) == shipped, name
