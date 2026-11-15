"""retraining/artifacts.py (V6.6.7: its own test file, the convention in tests/README.md; the deeper cases live in the round files)."""

from __future__ import annotations

from retraining.artifacts import candidate_dir, check_required_artifacts


def test_a_candidate_lives_under_versions_and_an_empty_one_lacks_everything(tmp_path):
    assert candidate_dir("v1", tmp_path) == tmp_path / "versions" / "v1"
    present, missing = check_required_artifacts(tmp_path, ("a.json", "b.pt"))
    assert present is False and set(missing) == {"a.json", "b.pt"}
    (tmp_path / "a.json").write_text("{}", encoding="utf-8")
    (tmp_path / "b.pt").write_bytes(b"x")
    assert check_required_artifacts(tmp_path, ("a.json", "b.pt"))[0] is True
