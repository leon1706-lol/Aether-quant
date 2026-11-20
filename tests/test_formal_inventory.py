"""scripts/formal_inventory.py (V6.6.10): every public function of the trading and research paths is proved, excluded with a reason,
or counted in a backlog that only shrinks; the repository passes its own gate."""

from __future__ import annotations

import json

from script_loader import load_script, run_script


def test_the_repository_passes_its_own_inventory():
    inventory = load_script("formal_inventory")
    found = inventory.problems(inventory.public_defs(), inventory.load_inventory(), specs=inventory.spec_targets())
    assert found == [], found[:10]


def test_every_kind_of_problem_is_named(tmp_path):
    inventory = load_script("formal_inventory")
    defs = {"pkg.a": ["f", "g", "h", "k"], "pkg.b": ["x"]}
    entries = {"modules": {"pkg.b": "backlog", "pkg.gone": "backlog"},
               "functions": {"pkg.a:f": "spec:Missing", "pkg.a:g": "excluded:vibes", "pkg.a:h": "spec:Real1", "pkg.a:old": "backlog"}}
    found = inventory.problems(defs, entries, specs={"Real1"}, ceiling=0)
    assert "pkg.a:k is not classified in formal/inventory.json" in found
    assert "pkg.a:f: formal/AetherFormal/Missing.lean does not exist" in found and "pkg.a:g: unknown status 'excluded:vibes'" in found
    assert "pkg.a:old is in formal/inventory.json but no longer exists" in found and any("pkg.gone" in line for line in found)
    assert any("above its ceiling 0" in line for line in found)
    assert inventory.status_of("pkg.b", "x", entries) == "backlog" and inventory.load_inventory(tmp_path / "none.json") == {"modules": {}, "functions": {}}


def test_the_report_counts_by_status_and_package():
    inventory = load_script("formal_inventory")
    counts = inventory.report({"pkg.a": ["f", "g"], "other.b": ["x"]}, {"modules": {"other.b": "excluded:io"}, "functions": {"pkg.a:f": "spec:T"}})
    assert counts == {"total": 3, "by_status": {"spec": 1, "unclassified": 1, "excluded": 1}, "by_package": {"other": {"excluded": 1}, "pkg": {"spec": 1, "unclassified": 1}}}


def test_main_exits_on_problems_and_prints_the_report(monkeypatch, capsys):
    inventory = load_script("formal_inventory")
    assert run_script("formal_inventory", ["--report"], monkeypatch) == 0 and '"total"' in capsys.readouterr().out
    assert inventory.main([]) == 0
    monkeypatch.setattr(inventory, "load_inventory", lambda: {"modules": {}, "functions": {}})
    assert inventory.main([]) == 1 and "is not classified" in capsys.readouterr().err
    assert json.loads((inventory.INVENTORY).read_text(encoding="utf-8"))["note"]
