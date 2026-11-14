"""scripts/v664_drop_eos.py (V6.6.6): the one-off that took EOS out of the forward definition, on a copy of the files."""

from __future__ import annotations

import json
import shutil

from script_loader import ROOT, load_script, run_script


def _tree(tmp_path, candidates):
    (tmp_path / "ml" / "forward").mkdir(parents=True)
    (tmp_path / "ml" / "forward" / "candidates.json").write_text(json.dumps({"candidates": candidates}), encoding="utf-8")
    shutil.copytree(ROOT / "ml" / "generations", tmp_path / "ml" / "generations")
    return tmp_path


def test_it_drops_the_coin_renames_the_candidate_and_records_the_change(tmp_path, monkeypatch, capsys):
    module = load_script("v664_drop_eos")
    old = {
        "id": module.OLD_ID, "tickers": ["BTCUSD", "EOSUSD"], "asset_class": {"BTCUSD": "crypto", "EOSUSD": "crypto"},
        "initial_weights": {"BTCUSD": 0.5, "EOSUSD": 0.5}, "kind": "time_series",
    }
    root = _tree(tmp_path, [{"id": "other"}, old])
    monkeypatch.setattr(module, "ROOT", root)
    lifecycle_before = (root / "ml" / "generations" / "lifecycle.jsonl").read_text(encoding="utf-8")

    assert module.main() == 0

    entry = json.loads((root / "ml" / "forward" / "candidates.json").read_text(encoding="utf-8"))["candidates"][1]
    assert entry["id"] == module.NEW_ID and entry["tickers"] == ["BTCUSD"] and "EOSUSD" not in entry["initial_weights"]
    registry = json.loads((root / "ml" / "generations" / "registry.json").read_text(encoding="utf-8"))
    assert "without EOS" in json.dumps(registry)
    added = (root / "ml" / "generations" / "lifecycle.jsonl").read_text(encoding="utf-8")[len(lifecycle_before):]
    assert '"definition_changed"' in added and json.loads(capsys.readouterr().out)["tickers"] == 1


def test_it_refuses_without_a_candidate_and_is_idempotent(tmp_path, monkeypatch, capsys):
    module = load_script("v664_drop_eos")
    monkeypatch.setattr(module, "ROOT", _tree(tmp_path, [{"id": "other"}]))
    assert module.main() == 1 and "no t3 candidate" in capsys.readouterr().err


def test_run_as_a_script_on_the_repository_it_is_already_done(monkeypatch, capsys):
    before = (ROOT / "ml" / "forward" / "candidates.json").read_bytes()
    assert run_script("v664_drop_eos", [], monkeypatch) == 0
    assert "already done" in capsys.readouterr().out and (ROOT / "ml" / "forward" / "candidates.json").read_bytes() == before
