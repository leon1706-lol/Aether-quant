"""Tests for retraining.artifacts — V2-17.

Conventions: no test classes, module-level helpers, real tmp_path
filesystem fixtures (no mocking needed — these are pure file operations).
"""

from pathlib import Path

from retraining.artifacts import (
    ACTIVE_ARTIFACT_FILES,
    ALL_TRACKED_FILES,
    OPTIONAL_GATING_FILES,
    OPTIONAL_TOPOLOGY_FILES,
    REQUIRED_CANDIDATE_FILES,
    check_gating_artifacts,
    check_required_artifacts,
    check_topology_artifacts,
    compute_artifact_hashes,
    copy_backtest_report_to_active,
    copy_candidate_to_active,
    restore_active_from_version,
)

_SMALL_FILES = ("model_weights.json", "training_metrics.json")


def _write_files(directory: Path, filenames, content="data") -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for name in filenames:
        (directory / name).write_text(content, encoding="utf-8")


def test_check_required_artifacts_detects_missing(tmp_path):
    version_dir = tmp_path / "versions" / "v1"
    _write_files(version_dir, ["model_weights.json"])

    present, missing = check_required_artifacts(version_dir, filenames=_SMALL_FILES)

    assert present is False
    assert missing == ["training_metrics.json"]


def test_check_required_artifacts_all_present(tmp_path):
    version_dir = tmp_path / "versions" / "v1"
    _write_files(version_dir, _SMALL_FILES)

    present, missing = check_required_artifacts(version_dir, filenames=_SMALL_FILES)

    assert present is True
    assert missing == []


def test_compute_artifact_hashes_is_deterministic(tmp_path):
    version_dir = tmp_path / "versions" / "v1"
    _write_files(version_dir, _SMALL_FILES, content="same-content")

    hashes_a = compute_artifact_hashes(version_dir, filenames=_SMALL_FILES)
    hashes_b = compute_artifact_hashes(version_dir, filenames=_SMALL_FILES)

    assert hashes_a == hashes_b
    assert set(hashes_a.keys()) == set(_SMALL_FILES)


def test_compute_artifact_hashes_differs_for_different_content(tmp_path):
    version_dir_a = tmp_path / "v_a"
    version_dir_b = tmp_path / "v_b"
    _write_files(version_dir_a, ["model_weights.json"], content="A")
    _write_files(version_dir_b, ["model_weights.json"], content="B")

    hashes_a = compute_artifact_hashes(version_dir_a, filenames=("model_weights.json",))
    hashes_b = compute_artifact_hashes(version_dir_b, filenames=("model_weights.json",))

    assert hashes_a["model_weights.json"] != hashes_b["model_weights.json"]


def test_copy_candidate_to_active_copies_files(tmp_path):
    version_dir = tmp_path / "versions" / "v1"
    ml_dir = tmp_path / "ml"
    _write_files(version_dir, _SMALL_FILES, content="candidate-content")

    hashes = copy_candidate_to_active(version_dir, ml_dir=ml_dir, filenames=_SMALL_FILES)

    for name in _SMALL_FILES:
        assert (ml_dir / name).exists()
        assert (ml_dir / name).read_text(encoding="utf-8") == "candidate-content"
    assert set(hashes.keys()) == set(_SMALL_FILES)


def test_restore_active_from_version_rejects_hash_mismatch(tmp_path):
    version_dir = tmp_path / "versions" / "v1"
    ml_dir = tmp_path / "ml"
    _write_files(version_dir, ["model_weights.json"], content="tampered")

    result = restore_active_from_version(
        version_dir,
        ml_dir=ml_dir,
        filenames=("model_weights.json",),
        expected_hashes={"model_weights.json": "0" * 64},
    )

    assert result["ok"] is False
    assert "model_weights.json" in result["mismatched"]
    assert not (ml_dir / "model_weights.json").exists()


def test_restore_active_from_version_succeeds_with_matching_hash(tmp_path):
    version_dir = tmp_path / "versions" / "v1"
    ml_dir = tmp_path / "ml"
    _write_files(version_dir, ["model_weights.json"], content="trusted-content")
    expected = compute_artifact_hashes(version_dir, filenames=("model_weights.json",))

    result = restore_active_from_version(
        version_dir, ml_dir=ml_dir, filenames=("model_weights.json",), expected_hashes=expected
    )

    assert result["ok"] is True
    assert (ml_dir / "model_weights.json").read_text(encoding="utf-8") == "trusted-content"


def test_restore_active_from_version_skips_verification_when_no_hashes_given(tmp_path):
    version_dir = tmp_path / "versions" / "v1"
    ml_dir = tmp_path / "ml"
    _write_files(version_dir, ["model_weights.json"], content="unverified")

    result = restore_active_from_version(version_dir, ml_dir=ml_dir, filenames=("model_weights.json",))

    assert result["ok"] is True
    assert (ml_dir / "model_weights.json").exists()


def test_active_artifact_files_matches_lean_runtime_requirements():
    # main.py's _validate_runtime_artifacts() requires exactly these three -
    # regression guard so promotion never drops one silently.
    for required in ("model_weights.json", "feature_schema.json", "scaler_stats.json"):
        assert required in ACTIVE_ARTIFACT_FILES


def test_copy_backtest_report_to_active(tmp_path):
    version_dir = tmp_path / "versions" / "v1"
    backtests_dir = tmp_path / "backtests"
    _write_files(version_dir, ["strategy_report.json", "equity_curves.csv"], content="report-data")

    copy_backtest_report_to_active(version_dir, backtests_dir)

    assert (backtests_dir / "strategy_report.json").read_text(encoding="utf-8") == "report-data"
    assert (backtests_dir / "equity_curves.csv").read_text(encoding="utf-8") == "report-data"


# -- V2-17.5 learned-topology artifacts --------------------------------------


def test_active_artifact_files_includes_topology_filenames():
    for filename in OPTIONAL_TOPOLOGY_FILES:
        assert filename in ACTIVE_ARTIFACT_FILES


def test_required_candidate_files_does_not_include_topology_filenames():
    # Topology training is best-effort - validate()'s gate must never
    # reject a candidate purely for missing topology artifacts.
    for filename in OPTIONAL_TOPOLOGY_FILES:
        assert filename not in REQUIRED_CANDIDATE_FILES


def test_all_tracked_files_is_union_of_required_and_topology():
    assert set(ALL_TRACKED_FILES) == set(REQUIRED_CANDIDATE_FILES) | set(OPTIONAL_TOPOLOGY_FILES) | set(OPTIONAL_GATING_FILES)


def test_copy_candidate_to_active_skips_missing_topology_files_gracefully(tmp_path):
    version_dir = tmp_path / "versions" / "v1"
    ml_dir = tmp_path / "ml"
    # Candidate has the required files but no topology artifacts at all.
    _write_files(version_dir, ("model_weights.json", "scaler.pkl", "scaler_stats.json", "training_metrics.json", "feature_schema.json"))

    hashes = copy_candidate_to_active(version_dir, ml_dir=ml_dir, filenames=ACTIVE_ARTIFACT_FILES)

    for filename in OPTIONAL_TOPOLOGY_FILES:
        assert filename not in hashes
        assert not (ml_dir / filename).exists()
    assert (ml_dir / "model_weights.json").exists()


def test_copy_candidate_to_active_includes_topology_files_when_present(tmp_path):
    version_dir = tmp_path / "versions" / "v1"
    ml_dir = tmp_path / "ml"
    _write_files(version_dir, ACTIVE_ARTIFACT_FILES, content="candidate-content")

    hashes = copy_candidate_to_active(version_dir, ml_dir=ml_dir, filenames=ACTIVE_ARTIFACT_FILES)

    for filename in OPTIONAL_TOPOLOGY_FILES:
        assert filename in hashes
        assert (ml_dir / filename).exists()


def test_check_topology_artifacts_reports_missing_without_failing(tmp_path):
    version_dir = tmp_path / "versions" / "v1"
    _write_files(version_dir, ["topology_model.json"])  # only one of three present

    present, missing = check_topology_artifacts(version_dir)

    assert present is False
    assert "topology_training_metrics.json" in missing
    assert "topology_feature_schema.json" in missing
    assert "topology_model.json" not in missing


def test_check_topology_artifacts_all_present(tmp_path):
    version_dir = tmp_path / "versions" / "v1"
    _write_files(version_dir, OPTIONAL_TOPOLOGY_FILES)

    present, missing = check_topology_artifacts(version_dir)

    assert present is True
    assert missing == []


# -- learned-gating artifacts -------------------------------------------------


def test_active_artifact_files_includes_gating_filenames():
    for filename in OPTIONAL_GATING_FILES:
        assert filename in ACTIVE_ARTIFACT_FILES


def test_required_candidate_files_does_not_include_gating_filenames():
    # Gating training is best-effort - validate()'s gate must never reject
    # a candidate purely for missing gating artifacts.
    for filename in OPTIONAL_GATING_FILES:
        assert filename not in REQUIRED_CANDIDATE_FILES


def test_copy_candidate_to_active_skips_missing_gating_files_gracefully(tmp_path):
    version_dir = tmp_path / "versions" / "v1"
    ml_dir = tmp_path / "ml"
    # Candidate has the required files but no gating artifacts at all.
    _write_files(version_dir, ("model_weights.json", "scaler.pkl", "scaler_stats.json", "training_metrics.json", "feature_schema.json"))

    hashes = copy_candidate_to_active(version_dir, ml_dir=ml_dir, filenames=ACTIVE_ARTIFACT_FILES)

    for filename in OPTIONAL_GATING_FILES:
        assert filename not in hashes
        assert not (ml_dir / filename).exists()
    assert (ml_dir / "model_weights.json").exists()


def test_copy_candidate_to_active_includes_gating_files_when_present(tmp_path):
    version_dir = tmp_path / "versions" / "v1"
    ml_dir = tmp_path / "ml"
    _write_files(version_dir, ACTIVE_ARTIFACT_FILES, content="candidate-content")

    hashes = copy_candidate_to_active(version_dir, ml_dir=ml_dir, filenames=ACTIVE_ARTIFACT_FILES)

    for filename in OPTIONAL_GATING_FILES:
        assert filename in hashes
        assert (ml_dir / filename).exists()


def test_check_gating_artifacts_reports_missing_without_failing(tmp_path):
    version_dir = tmp_path / "versions" / "v1"
    _write_files(version_dir, ["gating_model.json"])  # only one of three present

    present, missing = check_gating_artifacts(version_dir)

    assert present is False
    assert "gating_training_metrics.json" in missing
    assert "gating_feature_schema.json" in missing
    assert "gating_model.json" not in missing


def test_check_gating_artifacts_all_present(tmp_path):
    version_dir = tmp_path / "versions" / "v1"
    _write_files(version_dir, OPTIONAL_GATING_FILES)

    present, missing = check_gating_artifacts(version_dir)

    assert present is True
    assert missing == []
