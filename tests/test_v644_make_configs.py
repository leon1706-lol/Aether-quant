"""scripts/v644_make_configs.py and v650_make_recipe.py (V6.6.6): the round's fixed configs and the retrain recipe, written
by their command lines from a copy of the shipped config."""

from __future__ import annotations

import hashlib
import json

from script_loader import ROOT, block_path_writes, load_script, run_script


def test_every_grid_config_is_written_with_its_hash(tmp_path, monkeypatch, capsys):
    module = load_script("v644_make_configs")
    out = tmp_path / "configs"
    monkeypatch.setattr(module.sys, "argv", ["x", "--base", str(ROOT / "config.json"), "--out", str(out)])
    assert module.main() == 0
    shas = json.loads(capsys.readouterr().out)
    assert set(shas) == {"base_asof", *module.GRID}
    assert hashlib.sha256((out / "M1.json").read_bytes()).hexdigest() == shas["M1"]
    assert module.target_head({"rank_20d": 1.0}) == "rank_20d"


def test_the_recipe_is_written_to_its_place(monkeypatch, capsys):
    writes = block_path_writes(monkeypatch)
    assert run_script("v650_make_recipe", ["--end", "2023-12-29"], monkeypatch) == 0
    ((_method, path, args),) = [write for write in writes if write[0] == "write_text"]
    recipe = json.loads(args[0])
    assert path.name == "recipe.json" and recipe["phase1"]["universe"]["common_window"]["end"] == "2023-12-29"
    assert recipe["phase_v2"]["retraining"]["walk_forward"]["train_sequence"] is True and "recipe.json" in capsys.readouterr().out
