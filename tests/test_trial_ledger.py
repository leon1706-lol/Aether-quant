"""evaluation/trial_ledger.py: which runs count toward the deflated Sharpe's N and variance."""

import pytest

from evaluation.trial_ledger import VARIANCE_FLOOR, append_trial, candidate_ids, deflation_inputs, read_ledger

LEGACY = {"trials": [{"median_sharpe": 0.0}, {"median_sharpe": 1.0}, {"median_sharpe": -1.0}]}


def _add(path, trial_id, sharpe, window="selection", role="candidate"):
    return append_trial(path, trial_id=trial_id, track="T3", window=window, role=role, annualised_sharpe=sharpe, n_obs=100)


def test_round_trip_is_append_only(tmp_path):
    path = tmp_path / "ledger.jsonl"
    _add(path, "a", 0.5)
    _add(path, "b", None)

    entries = read_ledger(path)
    assert [entry["trial_id"] for entry in entries] == ["a", "b"]
    assert entries[1]["annualised_sharpe"] is None


def test_non_finite_sharpe_is_stored_as_none(tmp_path):
    assert _add(tmp_path / "l.jsonl", "a", float("nan"))["annualised_sharpe"] is None


def test_unknown_role_is_refused(tmp_path):
    with pytest.raises(ValueError, match="role"):
        _add(tmp_path / "l.jsonl", "a", 0.5, role="nonsense")


def test_read_of_a_missing_file_is_empty(tmp_path):
    assert read_ledger(tmp_path / "absent.jsonl") == []


def test_placebos_plumbing_and_verification_reads_add_no_trial(tmp_path):
    path = tmp_path / "l.jsonl"
    _add(path, "a", 0.5)
    _add(path, "p", 3.0, role="placebo")
    _add(path, "x", 3.0, role="plumbing")
    _add(path, "a", 1.0, window="verification", role="verification")

    entries = read_ledger(path)
    assert candidate_ids(entries) == {"a"}
    assert deflation_inputs(entries, LEGACY, "selection")["N"] == 4


def test_a_candidate_rescored_on_a_window_counts_once_by_its_last_score(tmp_path):
    path = tmp_path / "l.jsonl"
    _add(path, "a", 0.0)
    _add(path, "a", 2.0)
    _add(path, "b", 0.0)

    out = deflation_inputs(read_ledger(path), LEGACY, "selection")
    assert out["N"] == 5
    assert out["same_window_trials"] == 2
    assert out["var"] == pytest.approx(2.0)
    assert out["floored"] is False


def test_variance_uses_only_the_judged_window_and_has_a_floor(tmp_path):
    path = tmp_path / "l.jsonl"
    _add(path, "a", 0.50)
    _add(path, "b", 0.51)
    _add(path, "c", 9.0, window="other")

    out = deflation_inputs(read_ledger(path), LEGACY, "selection")
    assert out["var"] == VARIANCE_FLOOR
    assert out["floored"] is True
    assert out["same_window_trials"] == 2
    assert out["legacy_var"] == pytest.approx(1.0)


def test_no_scored_candidate_on_the_window_falls_back_to_the_floor():
    out = deflation_inputs([], LEGACY, "selection")
    assert out["var"] == VARIANCE_FLOOR
    assert out["N"] == 3
