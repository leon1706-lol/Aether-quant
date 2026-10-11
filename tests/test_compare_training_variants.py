"""scripts/compare_training_variants.py: winner selection on VALIDATION IC, against the control's own seed spread."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "compare_training_variants.py"
spec = importlib.util.spec_from_file_location("compare_training_variants", SCRIPT)
compare = importlib.util.module_from_spec(spec)
spec.loader.exec_module(compare)


def _metrics(val5, val20, bt5=0.1, bt20=0.1, seed=1):
    def block(mean):
        return {"mean_ic": mean, "t_stat": 2.0, "num_dates": 50}

    return {
        "seed": seed,
        "validation": {"rank_5d_ic_non_overlapping": block(val5), "rank_20d_ic_non_overlapping": block(val20)},
        "backtest": {
            "rank_5d_ic_non_overlapping": block(bt5),
            "rank_20d_ic_non_overlapping": block(bt20),
            "rank_5d_ranking_quality": {"quality_status": "promotable"},
            "rank_5d_net_performance": {"observed": {"net_sharpe": 1.2}},
        },
    }


def test_summary_scores_validation_not_backtest():
    row = compare.summarize_variant(_metrics(0.05, 0.07, bt5=0.9, bt20=0.9))

    assert row["validation_score"] == pytest.approx(0.06)
    assert row["heads"]["rank_5d"]["quality_status"] == "promotable"
    assert row["heads"]["rank_5d"]["net_sharpe"] == 1.2
    assert row["heads"]["rank_20d"]["quality_status"] is None


def test_the_full_daily_validation_ic_is_the_score_when_present_and_gets_a_hac_t_stat():
    metrics = _metrics(0.05, 0.07)
    daily = [0.10, 0.08, 0.12, 0.09, 0.11, 0.07, 0.10, 0.12, 0.08, 0.09, 0.11, 0.10]
    for head in ("rank_5d", "rank_20d"):
        metrics["validation"][f"{head}_ic"] = {"mean_ic": sum(daily) / len(daily), "ic_values": daily, "num_dates": len(daily)}
    row = compare.summarize_variant(metrics)
    assert row["validation_score"] == pytest.approx(sum(daily) / len(daily))  # not the 0.06 non-overlapping mean
    assert compare.summarize_variant(metrics, score_basis="non_overlapping")["validation_score"] == pytest.approx(0.06)
    hac = row["heads"]["rank_20d"]["validation"]["hac_t_stat"]
    assert hac is not None and hac > 0.0
    assert compare.summarize_variant(_metrics(0.05, 0.07))["heads"]["rank_5d"]["validation"]["hac_t_stat"] is None


def test_multi_seed_groups_are_scored_by_their_mean_against_the_controls_single_seed_spread():
    rows = {
        "c1": {"validation_score": 0.040, "heads": {}}, "c2": {"validation_score": 0.060, "heads": {}},
        "c3": {"validation_score": 0.050, "heads": {}},
        "good_a": {"validation_score": 0.080, "heads": {}}, "good_b": {"validation_score": 0.084, "heads": {}},
        "meh_a": {"validation_score": 0.062, "heads": {}}, "meh_b": {"validation_score": 0.068, "heads": {}},
        "unscored": {"validation_score": None, "heads": {}},
    }
    grouped = compare.group_rows(rows, {"control": ["c1", "c2", "c3"], "good": ["good_a", "good_b"], "meh": ["meh_a", "meh_b"], "none": ["unscored"]})
    assert grouped["control"]["validation_score"] == pytest.approx(0.05)
    assert grouped["none"]["validation_score"] is None
    verdict = compare.choose_group_winner(grouped, "control")
    assert verdict["seed_spread"] == pytest.approx(0.02)
    assert verdict["winner"] == "good" and verdict["beats_reference"] is True  # 0.082 > 0.05 + 0.02
    only_meh = compare.choose_group_winner({k: grouped[k] for k in ("control", "meh")}, "control")
    assert only_meh["winner"] == "control"  # 0.065 is inside the 0.02 noise band


def test_missing_or_non_finite_validation_ic_gives_no_score():
    assert compare.summarize_variant({})["validation_score"] is None
    assert compare.summarize_variant(_metrics(float("nan"), None))["validation_score"] is None


def test_a_variant_must_beat_the_control_by_more_than_its_seed_spread():
    rows = {
        "v0_s1": {"validation_score": 0.050},
        "v0_s2": {"validation_score": 0.058},
        "better": {"validation_score": 0.062},
        "marginal": {"validation_score": 0.056},
    }

    verdict = compare.choose_winner(rows, "v0_s1", ["v0_s1", "v0_s2"])

    assert verdict["seed_spread"] == pytest.approx(0.008)
    assert verdict["winner"] == "better" and verdict["beats_reference"] is True
    marginal_only = compare.choose_winner({k: rows[k] for k in ("v0_s1", "v0_s2", "marginal")}, "v0_s1", ["v0_s1", "v0_s2"])
    assert marginal_only["winner"] == "v0_s1" and marginal_only["beats_reference"] is False


def test_load_rows_skips_versions_without_metrics(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "multitask_training_metrics.json").write_text(json.dumps(_metrics(0.1, 0.1)), encoding="utf-8")

    rows = compare.load_rows(["a", "missing"], tmp_path, "multitask_training_metrics.json")

    assert list(rows) == ["a"]
