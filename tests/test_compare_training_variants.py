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
