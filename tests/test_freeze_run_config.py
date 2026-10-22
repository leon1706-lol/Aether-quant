"""scripts/freeze_run_config.py (V6.4.0): adopted changes onto a base config, never freezing a setting live code does not read."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
spec = importlib.util.spec_from_file_location("freeze_run_config", ROOT / "scripts" / "freeze_run_config.py")
freezer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(freezer)

BASE = {
    "runtime": {"lean_window_override": {"start": "2023-07-01", "end": "2026-10-16"}},
    "phase1": {"target": {"ranking": {"separate_rank_groups": {"forex": ["forex"]}}}},
    "phase_v2": {"portfolio_book": {"rebalance_every_bars": 20}, "exits": {"max_holding_bars": 40}, "risk": {"kill_switch": {}}},
}


def test_dotted_changes_land_under_phase_v2_and_patches_from_the_root():
    adopted = {"config": {"portfolio_book.rebalance_every_bars": 40, "exits.max_holding_bars": 60},
               "patch": {"phase1.target.ranking.separate_rank_groups": {"crypto": ["crypto"]}}, "needs_live_path": []}
    config = freezer.freeze(BASE, adopted)
    assert config["phase_v2"]["portfolio_book"]["rebalance_every_bars"] == 40 and config["phase_v2"]["exits"]["max_holding_bars"] == 60
    assert config["phase1"]["target"]["ranking"]["separate_rank_groups"] == {"crypto": ["crypto"]}
    assert BASE["phase_v2"]["portfolio_book"]["rebalance_every_bars"] == 20  # the base is untouched


def test_graduates_off_sets_the_crypto_core_only_knob():
    base = {**BASE, "phase_v2": {**BASE["phase_v2"], "class_weight_caps": {"crypto": {"exempt": ["BTCUSD"]}}}}
    config = freezer.freeze(base, {"config": {}, "graduates_off": True, "needs_live_path": ["graduates_off"]})
    assert config["phase_v2"]["class_weight_caps"]["crypto"] == {"exempt": ["BTCUSD"], "core_only": True}
    assert "core_only" not in base["phase_v2"]["class_weight_caps"]["crypto"]


def test_an_empty_ship_list_is_the_base_config():
    assert freezer.freeze(BASE, {"config": {}, "patch": {}, "needs_live_path": []}) == BASE


def test_an_item_without_a_live_path_is_refused():
    with pytest.raises(ValueError, match="tranches"):
        freezer.freeze(BASE, {"config": {}, "needs_live_path": ["tranches"]})


def test_the_lean_window_is_set_when_asked():
    config = freezer.freeze(BASE, {"config": {}}, ("2023-07-01", "2026-10-16"))
    assert config["runtime"]["lean_window_override"] == {"start": "2023-07-01", "end": "2026-10-16"}
