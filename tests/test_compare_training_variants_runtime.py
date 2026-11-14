"""scripts/compare_training_variants.py's runtime (V6.6.6, #359): the winner choice among single versions, the group winner against the control's seed spread, the
version loader, and `main()` in its table mode and its multi-seed group mode, on small metrics files."""

from __future__ import annotations

import json
import sys

import pytest

from script_loader import load_script


@pytest.fixture
def module():
    return load_script("compare_training_variants")


def _metrics(val5, val20, *, daily=True):
    def block(mean):
        return {"mean_ic": mean, "t_stat": 2.0, "num_dates": 50}

    out = {"seed": 1, "validation": {"rank_5d_ic_non_overlapping": block(val5), "rank_20d_ic_non_overlapping": block(val20)},
           "backtest": {"rank_5d_ic_non_overlapping": block(0.1), "rank_20d_ic_non_overlapping": block(None), "rank_5d_ranking_quality": {"quality_status": "promotable"}}}
    if daily:
        out["validation"]["rank_5d_ic"] = {"mean_ic": val5, "ic_values": [val5, val5 + 0.01, val5 - 0.01, val5, val5 + 0.02, val5 - 0.02, val5, val5, val5 + 0.01, val5 - 0.01], "num_dates": 10}
    return out


def _write(folder, version, metrics):
    (folder / version).mkdir(parents=True, exist_ok=True)
    (folder / version / "multitask_training_metrics.json").write_text(json.dumps(metrics), encoding="utf-8")


def test_a_variant_wins_only_above_the_references_score_plus_the_noise_between_its_seeds(module):
    rows = {"ref": {"validation_score": 0.05}, "noise": {"validation_score": 0.06}, "better": {"validation_score": 0.09}, "best": {"validation_score": 0.12}, "none": {"validation_score": None}, "close": {"validation_score": 0.055}}
    verdict = module.choose_winner(rows, "ref", ["ref", "noise", "ghost"])
    assert verdict["winner"] == "best" and verdict["beats_reference"] is True and verdict["seed_spread"] == pytest.approx(0.01)
    assert module.choose_winner({"ref": {"validation_score": None}, "x": {"validation_score": 1.0}}, "ref", ["ref"])["winner"] == "ref"
    assert module.choose_winner({"x": {"validation_score": 1.0}}, "ref", ["ref"])["reference_score"] is None


def test_a_group_wins_only_when_its_mean_clears_the_controls_own_seed_spread(module):
    grouped = {"control": {"validation_score": 0.05, "member_scores": {"c1": 0.04, "c2": 0.06}}, "good": {"validation_score": 0.09, "member_scores": {}}, "weak": {"validation_score": 0.06, "member_scores": {}},
               "empty": {"validation_score": None, "member_scores": {}}, "better": {"validation_score": 0.1, "member_scores": {}}}
    verdict = module.choose_group_winner(grouped, "control")
    assert verdict["winner"] == "better" and verdict["seed_spread"] == pytest.approx(0.02)
    assert module.choose_group_winner({"good": {"validation_score": 0.09, "member_scores": {}}}, "control")["winner"] == "control"


def test_only_versions_with_a_metrics_file_are_loaded(module, tmp_path):
    _write(tmp_path, "v1", _metrics(0.05, 0.07))
    assert set(module.load_rows(["v1", "gone"], tmp_path, "multitask_training_metrics.json")) == {"v1"}


def test_the_table_mode_compares_every_version_against_the_reference(module, monkeypatch, tmp_path, capsys):
    _write(tmp_path, "ref", _metrics(0.04, 0.04))
    _write(tmp_path, "noise", _metrics(0.05, 0.05, daily=False))
    _write(tmp_path, "v1", _metrics(0.2, 0.2))
    out = tmp_path / "out" / "comparison.json"
    monkeypatch.setattr(sys, "argv", ["compare", "--versions-dir", str(tmp_path), "--reference", "ref", "--noise", "noise", "--variants", "v1", "ghost", "--output", str(out)])
    assert module.main() == 0
    written = json.loads(out.read_text(encoding="utf-8"))
    printed = capsys.readouterr().out
    assert written["verdict"]["winner"] == "v1" and set(written["rows"]) == {"ref", "noise", "v1"} and "n/a" in printed and "promotable" in printed


def test_a_version_with_no_usable_validation_score_prints_na_in_the_table(module, monkeypatch, tmp_path, capsys):
    _write(tmp_path, "ref", {"validation": {}, "backtest": {}})
    monkeypatch.setattr(sys, "argv", ["compare", "--versions-dir", str(tmp_path), "--reference", "ref", "--output", str(tmp_path / "o.json")])
    assert module.main() == 0 and " n/a " in capsys.readouterr().out


def test_the_group_mode_scores_each_arm_by_its_mean_and_names_a_winner(module, monkeypatch, tmp_path, capsys):
    for version, value in (("c1", 0.04), ("c2", 0.05), ("g1", 0.2), ("g2", 0.22)):
        _write(tmp_path, version, _metrics(value, value, daily=False))
    out = tmp_path / "groups" / "comparison.json"
    monkeypatch.setattr(sys, "argv", ["compare", "--versions-dir", str(tmp_path), "--reference", "control", "--groups", "control=c1,c2", "good=g1,g2", "lost=nope", "--output", str(out)])
    assert module.main() == 0
    written = json.loads(out.read_text(encoding="utf-8"))
    assert written["verdict"]["winner"] == "good" and written["groups"]["lost"]["validation_score"] is None and "n/a" in capsys.readouterr().out
