"""scripts/v643_microbench.py (V6.6.6): the hot-path functions against their committed versions, identical outputs or a failure."""

from __future__ import annotations

import json
from types import SimpleNamespace

from script_loader import load_script


def test_the_committed_and_current_versions_agree_and_are_timed(tmp_path, monkeypatch, capsys):
    module = load_script("v643_microbench")
    out = tmp_path / "bench" / "microbench.json"
    monkeypatch.setattr(module.sys, "argv", ["x", "--calls", "200", "--out", str(out)])
    assert module.main() == 0
    report = json.loads(out.read_text(encoding="utf-8"))
    assert set(report) == {"apply_book_neutrality", "cap_target_weight", "build_dynamic_position_sizing", "trailing_drawdown"}
    assert all(row["identical_outputs"] for row in report.values()) and "cap_target_weight" in capsys.readouterr().out


def test_a_changed_output_fails_the_bench(tmp_path, monkeypatch):
    module = load_script("v643_microbench")
    different = SimpleNamespace(
        apply_book_neutrality=lambda weights, sector_by_symbol, **kwargs: ({}, {}), cap_target_weight=lambda *args: 99.0,
        build_dynamic_position_sizing=lambda *args: SimpleNamespace(target_weight=99.0), trailing_drawdown=lambda series, window: 99.0,
    )
    monkeypatch.setattr(module, "_committed_module", lambda name, relative, tmp: different)
    monkeypatch.setattr(module.sys, "argv", ["x", "--calls", "200", "--out", str(tmp_path / "m.json")])
    assert module.main() == 1
