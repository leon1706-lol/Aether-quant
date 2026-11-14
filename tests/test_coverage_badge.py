"""scripts/coverage_badge.py (V6.6.6): the coverage figure for CI's summary and the README's endpoint badge."""

from __future__ import annotations

import json

import pytest

from script_loader import load_script, run_script


@pytest.mark.parametrize(("percent", "color"), [(100.0, "brightgreen"), (90.0, "brightgreen"), (85.0, "green"), (72.0, "yellow"), (40.0, "red")])
def test_the_color_follows_the_figure(percent, color):
    module = load_script("coverage_badge")
    assert module.color_for(percent) == color
    assert module.badge(percent) == {"schemaVersion": 1, "label": "coverage", "message": f"{percent:.0f}%", "color": color}


def test_the_summary_and_the_badge_file(tmp_path, monkeypatch, capsys):
    report = tmp_path / "coverage.json"
    report.write_text(json.dumps({"totals": {"percent_covered": 99.5, "covered_lines": 199, "num_statements": 200}}), encoding="utf-8")
    badge = tmp_path / "site" / "badges" / "coverage.json"
    assert run_script("coverage_badge", [str(report), "--badge", str(badge), "--label", "python coverage"], monkeypatch) == 0
    assert "## python coverage: 99.5% (199 of 200 lines)" in capsys.readouterr().out
    assert json.loads(badge.read_text(encoding="utf-8")) == {"schemaVersion": 1, "label": "python coverage", "message": "100%", "color": "brightgreen"}
    assert run_script("coverage_badge", [str(report)], monkeypatch) == 0


def test_a_missing_or_malformed_report_is_an_error(tmp_path, monkeypatch, capsys):
    assert run_script("coverage_badge", [str(tmp_path / "none.json")], monkeypatch) == 1
    (tmp_path / "bad.json").write_text("{}", encoding="utf-8")
    assert run_script("coverage_badge", [str(tmp_path / "bad.json")], monkeypatch) == 1
    assert "no coverage figures" in capsys.readouterr().err
