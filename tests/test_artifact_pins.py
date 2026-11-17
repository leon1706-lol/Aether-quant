"""retraining/artifact_pins.py: the installed model set is pinned, and a rewritten member is found (V6.6.9, #382)."""

from __future__ import annotations

import json

from retraining.artifact_pins import (
    PINNED_FILES,
    artifact_problems,
    check_artifact_pins,
    compute_artifact_pins,
    file_sha256,
    load_artifact_pins,
    snapshot_active,
    write_artifact_pins,
)


def _ml(tmp_path):
    ml = tmp_path / "ml"
    (ml / "expert_models" / "bullish").mkdir(parents=True)
    (ml / "model_weights.json").write_text('{"w": 1}', encoding="utf-8")
    (ml / "scaler_stats.json").write_text('{"mean": [0.0007], "scale": [0.0228]}', encoding="utf-8")
    (ml / "expert_models" / "bullish" / "model_weights.json").write_text("{}", encoding="utf-8")
    (ml / "notes.txt").write_text("not a model file", encoding="utf-8")
    return ml


def test_only_the_files_main_loads_that_exist_are_pinned(tmp_path):
    ml = _ml(tmp_path)
    pins = compute_artifact_pins(ml)
    assert set(pins) == {"model_weights.json", "scaler_stats.json", "expert_models/bullish/model_weights.json"}
    assert pins["scaler_stats.json"] == file_sha256(ml / "scaler_stats.json")
    assert "scaler_stats.json" in PINNED_FILES and "sequence_model.json" in PINNED_FILES


def test_a_written_record_reads_back_and_a_healthy_set_has_no_problem(tmp_path):
    ml = _ml(tmp_path)
    record = tmp_path / "ml" / "artifact_pins.json"
    pins = write_artifact_pins(ml, record)
    assert load_artifact_pins(record) == pins
    assert record.read_bytes().endswith(b"\n") and b"\r" not in record.read_bytes()
    assert check_artifact_pins(ml, pins) == []
    assert artifact_problems(ml, record) == []


def test_a_rewritten_scaler_and_a_missing_model_are_both_named(tmp_path):
    """What happened on 2026-11-14: the scaler was refitted under models that stayed the same."""
    ml = _ml(tmp_path)
    record = tmp_path / "pins.json"
    pins = write_artifact_pins(ml, record)
    (ml / "scaler_stats.json").write_text('{"mean": [-0.00001], "scale": [0.0109]}', encoding="utf-8")
    (ml / "model_weights.json").unlink()
    assert check_artifact_pins(ml, pins) == ["model_weights.json", "scaler_stats.json"]
    assert artifact_problems(ml, record) == ["model_weights.json does not match its pin", "scaler_stats.json does not match its pin"]


def test_no_record_is_a_problem_and_a_damaged_record_pins_nothing(tmp_path):
    ml = _ml(tmp_path)
    assert artifact_problems(ml, tmp_path / "absent.json") == ["no artifact pins at absent.json"]
    damaged = tmp_path / "damaged.json"
    damaged.write_text("{not json", encoding="utf-8")
    assert load_artifact_pins(damaged) == {}
    for payload in ([1, 2], {"files": "nope"}):
        damaged.write_text(json.dumps(payload), encoding="utf-8")
        assert load_artifact_pins(damaged) == {}
    assert check_artifact_pins(ml, {}) == []


def test_snapshot_active_zips_what_is_pinned_and_the_record(tmp_path):
    import zipfile

    ml = tmp_path / "ml"
    ml.mkdir()
    (ml / "scaler_stats.json").write_text("{}", encoding="utf-8")
    (ml / "sequence_model.json").write_text("{}", encoding="utf-8")
    (ml / "unpinned.json").write_text("{}", encoding="utf-8")
    write_artifact_pins(ml, ml / "artifact_pins.json")
    target = snapshot_active(ml, tmp_path / "backups" / "pre_retrain_r1.zip")
    with zipfile.ZipFile(target) as archive:
        assert sorted(archive.namelist()) == ["ml/artifact_pins.json", "ml/scaler_stats.json", "ml/sequence_model.json"]
    bare = tmp_path / "bare"
    bare.mkdir()
    (bare / "scaler_stats.json").write_text("{}", encoding="utf-8")
    with zipfile.ZipFile(snapshot_active(bare, tmp_path / "bare.zip")) as archive:
        assert archive.namelist() == ["ml/scaler_stats.json"]
