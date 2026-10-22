"""Static checks of scripts/codespace_session_v640.sh (V6.4.0): the session is one Codespace lifetime that cannot run in the
suite, so these pin the guards a past session needed - the model manifest, the append-only data check, the dataset diff that
may only add rows, the smoke pass before the long chain, the frozen yardstick, and the stop on a failed step."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SESSION = (ROOT / "scripts" / "codespace_session_v640.sh").read_bytes().decode("utf-8")


def test_session_script_has_lf_endings_and_is_resumable():
    assert "\r\n" not in SESSION
    assert 'marker() { [ "${RESUME:-0}" = "1" ]' in SESSION


def test_session_checks_the_models_and_the_data_before_spending_hours():
    assert SESSION.index("MANIFEST MISMATCH") < SESSION.index("S1 full-split dataset")
    assert SESSION.index("data_append_guard.py verify") < SESSION.index("S1 full-split dataset")
    assert "factor_file_backfill --audit" in SESSION


def test_dataset_may_only_add_rows_and_resolve_labels():
    assert "startswith(\"target_\")" in SESSION and "ALLOW_FEATURE_DRIFT" in SESSION
    assert "the dataset build changed the installed models" in SESSION


def test_retrain_uses_the_subset_schema_and_five_seeds():
    assert "for seed in 1 2 3 4 5" in SESSION
    assert "--feature-schema-path \"${OUT}/schema_mt_leg.json\"" in SESSION
    assert "ml/datasets/v640_legacy_dataset.csv" in SESSION


def test_candidate_yardstick_is_the_owners_0_034():
    assert '"yardstick": 0.034' in SESSION
    assert "--rule r-model10 --prefix v640_cand_" in SESSION


def test_a_smoke_pass_runs_before_the_real_chain_and_a_failure_stops_the_session():
    assert SESSION.index("--smoke") < SESSION.index("S5b the research chain")
    assert SESSION.count("exit 1") >= 8
    assert "--lean-run \"${BT4}\"" in SESSION


def test_session_ends_with_the_suite_and_a_pack_of_what_it_wrote():
    assert "codespace_run_tests.sh" in SESSION
    assert "tar czf /tmp/eval_pack.tgz" in SESSION and "SESSION DONE" in SESSION
