"""V5.3.7 - tests for the promotion gate's era_rule selector
(train.py::assess_ranking_quality). Legacy mode must stay byte-identical to
the historical any-flip behavior; flip_fraction mode skips the hard
any-flip failure and delegates blocking to max_era_sign_flip_fraction."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

train = pytest.importorskip("train")


def _base_inputs():
    non_overlapping = {"t_stat": 2.6, "mean_ic": 0.05}
    bootstrap = {"lower_bound": 0.01}
    per_era = [
        {"era_index": i, "era_start": f"2019-0{i+1}-01", "era_end": f"2019-0{i+1}-28",
         "num_dates": 12, "mean_ic": mean_ic}
        for i, mean_ic in enumerate([0.10, 0.08, -0.06, 0.09, -0.07])
    ]
    return non_overlapping, bootstrap, per_era


def _config(era_rule: str, max_flip_fraction: float):
    return {
        "phase1": {
            "target": {
                "ranking": {
                    "promotion_gate": {
                        "min_non_overlapping_t_stat": 2.0,
                        "min_bootstrap_ci_lower": 0.0,
                        "era_sign_min_abs_ic": 0.05,
                        "era_min_observations": 3,
                        "max_era_sign_flip_fraction": max_flip_fraction,
                        "era_rule": era_rule,
                    }
                }
            }
        }
    }


def test_legacy_mode_fails_on_any_opposite_sign_era():
    non_overlapping, bootstrap, per_era = _base_inputs()
    result = train.assess_ranking_quality(non_overlapping, bootstrap, per_era, _config("legacy", 1.0))
    assert "era_sign_instability" in result["failures"]
    assert result["quality_status"] == "not_promotable"
    assert result["thresholds"]["era_rule"] == "legacy"


def test_flip_fraction_mode_within_calibrated_knob_passes():
    # 2/5 eras flipped = fraction 0.4 > knob 0.34 would FAIL; use knob 0.5.
    non_overlapping, bootstrap, per_era = _base_inputs()
    result = train.assess_ranking_quality(non_overlapping, bootstrap, per_era, _config("flip_fraction", 0.5))
    assert "era_sign_instability" not in result["failures"]
    assert result["failures"] == []
    # The flipped eras become a recorded NEAR-MISS diagnostic in this mode;
    # eligibility is unaffected (the calibrated fraction knob owns blocking).
    assert result["quality_status"] == "watchlist"
    assert result["promotion_eligible"] is True
    assert "era_sign_instability_flip_fraction_mode" in result["near_misses"]


def test_flip_fraction_mode_above_calibrated_knob_fails():
    non_overlapping, bootstrap, per_era = _base_inputs()
    result = train.assess_ranking_quality(non_overlapping, bootstrap, per_era, _config("flip_fraction", 0.34))
    assert "era_sign_flip_fraction_above_gate" in result["failures"]
    assert result["quality_status"] == "not_promotable"


def test_legacy_default_when_key_absent():
    cfg = _config("flip_fraction", 1.0)
    del cfg["phase1"]["target"]["ranking"]["promotion_gate"]["era_rule"]
    non_overlapping, bootstrap, per_era = _base_inputs()
    result = train.assess_ranking_quality(non_overlapping, bootstrap, per_era, cfg)
    assert "era_sign_instability" in result["failures"]
    assert result["thresholds"]["era_rule"] == "legacy"


def test_config_json_ships_flip_fraction_rule():
    config_path = Path(__file__).resolve().parents[1] / "config.json"
    gate = json.loads(config_path.read_text(encoding="utf-8"))["phase1"]["target"]["ranking"]["promotion_gate"]
    assert gate.get("era_rule") == "flip_fraction"
    assert 0 < float(gate["max_era_sign_flip_fraction"]) < 1.0


def test_t_and_ci_gates_still_apply_in_flip_fraction_mode():
    non_overlapping, bootstrap, per_era = _base_inputs()
    weak = {"t_stat": 1.2, "mean_ic": 0.02}
    result = train.assess_ranking_quality(weak, bootstrap, per_era, _config("flip_fraction", 0.5))
    assert "non_overlapping_t_stat_below_gate" in result["failures"]
