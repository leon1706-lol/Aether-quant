"""Tests for retraining.orchestrator — V2-17.

Conventions: no test classes, module-level helpers, MagicMock conn injection
plus patching subprocess.run / retraining.artifacts primitives so these stay
unit tests (no real Postgres, no real train.py subprocess).
"""

from unittest.mock import MagicMock, patch

from retraining import orchestrator


def _make_conn_mock():
    conn_mock = MagicMock()
    cur_mock = MagicMock()
    conn_mock.cursor.return_value.__enter__.return_value = cur_mock
    conn_mock.cursor.return_value.__exit__.return_value = False
    return conn_mock, cur_mock


def test_train_invokes_train_py_with_candidate_and_version_id_flags():
    conn_mock, _ = _make_conn_mock()
    completed = MagicMock(returncode=0, stdout="ok", stderr="")

    with patch("retraining.orchestrator.subprocess.run", return_value=completed) as run_mock, patch(
        "retraining.orchestrator.update_retraining_event_status"
    ), patch("retraining.orchestrator.insert_model_version"):
        result = orchestrator.train(conn_mock, retraining_id="r1", version_id="v1")

    argv = run_mock.call_args.args[0]
    assert "--candidate" in argv
    assert "--version-id" in argv
    assert "v1" in argv
    assert result["ok"] is True
    # train.py is invoked as a subprocess (never imported in-process), and the
    # orchestrator itself never touches ml/model_weights.json or any other
    # active-path constant directly - it only shells out and reads back
    # ml/versions/<id>/ artifacts in later stages.


def test_train_marks_event_failed_when_subprocess_fails():
    conn_mock, _ = _make_conn_mock()
    completed = MagicMock(returncode=1, stdout="", stderr="boom")

    with patch("retraining.orchestrator.subprocess.run", return_value=completed), patch(
        "retraining.orchestrator.update_retraining_event_status"
    ) as update_event_mock, patch("retraining.orchestrator.update_model_version_status") as update_version_mock, patch(
        "retraining.orchestrator.insert_model_version"
    ):
        result = orchestrator.train(conn_mock, retraining_id="r1", version_id="v1")

    assert result["ok"] is False
    update_event_mock.assert_any_call(conn_mock, "r1", status="failed", notes=[{"stage": "train", "returncode": 1, "stderr": "boom"}])
    update_version_mock.assert_called_with(conn_mock, "v1", status="rejected")


def test_promote_requires_vault_commit():
    conn_mock, _ = _make_conn_mock()
    candidate_without_commit = {"model_version_id": "v1", "status": "candidate", "aether_vault_commit": None}

    with patch("retraining.orchestrator.fetch_model_version", return_value=candidate_without_commit), patch(
        "retraining.orchestrator.copy_candidate_to_active"
    ) as copy_mock, patch("retraining.orchestrator.promote_model_version") as promote_mock:
        result = orchestrator.promote(conn_mock, "v1")

    assert result["ok"] is False
    assert result["error"] == "promotion_requires_vault_commit"
    copy_mock.assert_not_called()
    promote_mock.assert_not_called()


def test_promote_requires_candidate_status():
    conn_mock, _ = _make_conn_mock()
    already_active = {"model_version_id": "v1", "status": "active", "aether_vault_commit": "abc123"}

    with patch("retraining.orchestrator.fetch_model_version", return_value=already_active):
        result = orchestrator.promote(conn_mock, "v1")

    assert result["ok"] is False
    assert result["error"] == "promotion_requires_validated_candidate_status"


def test_promote_succeeds_when_candidate_has_vault_commit():
    conn_mock, _ = _make_conn_mock()
    candidate = {"model_version_id": "v1", "status": "candidate", "aether_vault_commit": "abc123"}

    with patch("retraining.orchestrator.fetch_model_version", return_value=candidate), patch(
        "retraining.orchestrator.fetch_active_model_version", return_value=None
    ), patch("retraining.orchestrator.copy_candidate_to_active", return_value={"model_weights.json": "hash"}), patch(
        "retraining.orchestrator.copy_backtest_report_to_active"
    ), patch("retraining.orchestrator.promote_model_version") as promote_mock, patch(
        "retraining.orchestrator.update_model_version_status"
    ), patch("retraining.orchestrator.write_status_file"), patch(
        "retraining.orchestrator.build_status_view", return_value={}
    ), patch("retraining.orchestrator.write_manual_trade_lock_override") as override_mock:
        result = orchestrator.promote(conn_mock, "v1")

    assert result["ok"] is True
    promote_mock.assert_called_once_with(conn_mock, old_active_id=None, new_active_id="v1")
    # auto_clear_trade_lock defaults to True when config is omitted entirely.
    override_mock.assert_called_once_with(False, orchestrator._CONFIG_PATH)


def _patched_promote(conn_mock, candidate, config=None):
    with patch("retraining.orchestrator.fetch_model_version", return_value=candidate), patch(
        "retraining.orchestrator.fetch_active_model_version", return_value=None
    ), patch("retraining.orchestrator.copy_candidate_to_active", return_value={"model_weights.json": "hash"}), patch(
        "retraining.orchestrator.copy_backtest_report_to_active"
    ), patch("retraining.orchestrator.promote_model_version"), patch(
        "retraining.orchestrator.update_model_version_status"
    ), patch("retraining.orchestrator.write_status_file"), patch(
        "retraining.orchestrator.build_status_view", return_value={}
    ), patch("retraining.orchestrator.write_manual_trade_lock_override") as override_mock:
        result = orchestrator.promote(conn_mock, "v1", config=config)
    return result, override_mock


def test_promote_clears_trade_lock_override_by_default():
    conn_mock, _ = _make_conn_mock()
    candidate = {"model_version_id": "v1", "status": "candidate", "aether_vault_commit": "abc123"}

    result, override_mock = _patched_promote(conn_mock, candidate, config={})

    assert result["ok"] is True
    override_mock.assert_called_once_with(False, orchestrator._CONFIG_PATH)


def test_promote_skips_clearing_trade_lock_when_disabled_in_config():
    conn_mock, _ = _make_conn_mock()
    candidate = {"model_version_id": "v1", "status": "candidate", "aether_vault_commit": "abc123"}

    result, override_mock = _patched_promote(
        conn_mock, candidate, config={"promotion": {"auto_clear_trade_lock": False}}
    )

    assert result["ok"] is True
    override_mock.assert_not_called()


def test_rollback_restores_previous_active_version_metadata():
    conn_mock, _ = _make_conn_mock()
    target = {"model_version_id": "v_old", "status": "archived", "artifact_hashes": {"model_weights.json": "h"}}
    current_active = {"model_version_id": "v_new"}

    with patch("retraining.orchestrator.fetch_model_version", return_value=target), patch(
        "retraining.orchestrator.restore_active_from_version", return_value={"ok": True, "hashes": {}, "mismatched": []}
    ), patch("retraining.orchestrator.fetch_active_model_version", return_value=current_active), patch(
        "retraining.orchestrator.promote_model_version"
    ) as promote_mock, patch("retraining.orchestrator.update_model_version_status") as update_mock, patch(
        "retraining.orchestrator.insert_retraining_event"
    ) as insert_event_mock, patch("retraining.orchestrator.write_status_file"), patch(
        "retraining.orchestrator.build_status_view", return_value={}
    ):
        result = orchestrator.rollback(conn_mock, "v_old")

    assert result["ok"] is True
    promote_mock.assert_called_once_with(conn_mock, old_active_id="v_new", new_active_id="v_old")
    update_mock.assert_any_call(conn_mock, "v_old", status="active")
    update_mock.assert_any_call(conn_mock, "v_new", status="rolled_back")
    insert_event_mock.assert_called_once()
    event_arg = insert_event_mock.call_args.args[1]
    assert event_arg["candidate_version_id"] == "v_old"
    assert event_arg["status"] == "promoted"


def test_rollback_fails_when_artifacts_hash_mismatch():
    conn_mock, _ = _make_conn_mock()
    target = {"model_version_id": "v_old", "status": "archived", "artifact_hashes": {}, "aether_vault_commit": None}

    with patch("retraining.orchestrator.fetch_model_version", return_value=target), patch(
        "retraining.orchestrator.restore_active_from_version",
        return_value={"ok": False, "hashes": {}, "mismatched": ["model_weights.json"]},
    ), patch("retraining.orchestrator.promote_model_version") as promote_mock:
        result = orchestrator.rollback(conn_mock, "v_old")

    assert result["ok"] is False
    assert result["error"] == "artifact_hash_mismatch"
    promote_mock.assert_not_called()


def test_rollback_rejects_ineligible_target_status():
    conn_mock, _ = _make_conn_mock()
    target = {"model_version_id": "v_old", "status": "candidate"}

    with patch("retraining.orchestrator.fetch_model_version", return_value=target):
        result = orchestrator.rollback(conn_mock, "v_old")

    assert result["ok"] is False
    assert result["error"] == "rollback_target_not_eligible"


# -- V2-17.5 learned-topology training stage ---------------------------------


def test_train_topology_invokes_script_with_version_id_flag():
    conn_mock, _ = _make_conn_mock()
    completed = MagicMock(returncode=0, stdout="ok", stderr="")

    with patch("retraining.orchestrator.subprocess.run", return_value=completed) as run_mock:
        result = orchestrator.train_topology(conn_mock, retraining_id="r1", version_id="v1", config={})

    argv = run_mock.call_args.args[0]
    assert "train_topology.py" in argv[1]
    assert "--version-id" in argv
    assert "v1" in argv
    assert result["ok"] is True


def test_train_topology_subprocess_failure_does_not_reject_model_version():
    """Unlike train()'s hard failure path, a topology-training subprocess
    failure must never reject the candidate model_version - topology
    artifacts are optional (see retraining/artifacts.py's
    OPTIONAL_TOPOLOGY_FILES)."""
    conn_mock, _ = _make_conn_mock()
    completed = MagicMock(returncode=1, stdout="", stderr="topology boom")

    with patch("retraining.orchestrator.subprocess.run", return_value=completed), patch(
        "retraining.orchestrator.update_retraining_event_status"
    ) as update_event_mock, patch("retraining.orchestrator.update_model_version_status") as update_version_mock:
        result = orchestrator.train_topology(conn_mock, retraining_id="r1", version_id="v1", config={})

    assert result["ok"] is False
    update_version_mock.assert_not_called()
    update_event_mock.assert_called_once()
    assert update_event_mock.call_args.kwargs["status"] == "running"


def test_train_topology_disabled_returns_early_without_subprocess():
    conn_mock, _ = _make_conn_mock()

    with patch("retraining.orchestrator.subprocess.run") as run_mock:
        result = orchestrator.train_topology(
            conn_mock, retraining_id="r1", version_id="v1", config={"topology_training": {"enabled": False}}
        )

    assert result["ok"] is False
    assert result["reason"] == "topology_training_disabled"
    run_mock.assert_not_called()


# -- learned-gating training stage --------------------------------------------


def test_train_gating_invokes_script_with_version_id_flag():
    conn_mock, _ = _make_conn_mock()
    completed = MagicMock(returncode=0, stdout="ok", stderr="")

    with patch("retraining.orchestrator.subprocess.run", return_value=completed) as run_mock:
        result = orchestrator.train_gating(conn_mock, retraining_id="r1", version_id="v1", config={})

    argv = run_mock.call_args.args[0]
    assert "train_gating.py" in argv[1]
    assert "--version-id" in argv
    assert "v1" in argv
    assert result["ok"] is True


def test_train_gating_subprocess_failure_does_not_reject_model_version():
    """Unlike train()'s hard failure path, a gating-training subprocess
    failure must never reject the candidate model_version - gating
    artifacts are optional (see retraining/artifacts.py's
    OPTIONAL_GATING_FILES)."""
    conn_mock, _ = _make_conn_mock()
    completed = MagicMock(returncode=1, stdout="", stderr="gating boom")

    with patch("retraining.orchestrator.subprocess.run", return_value=completed), patch(
        "retraining.orchestrator.update_retraining_event_status"
    ) as update_event_mock, patch("retraining.orchestrator.update_model_version_status") as update_version_mock:
        result = orchestrator.train_gating(conn_mock, retraining_id="r1", version_id="v1", config={})

    assert result["ok"] is False
    update_version_mock.assert_not_called()
    update_event_mock.assert_called_once()
    assert update_event_mock.call_args.kwargs["status"] == "running"


def test_train_gating_disabled_returns_early_without_subprocess():
    conn_mock, _ = _make_conn_mock()

    with patch("retraining.orchestrator.subprocess.run") as run_mock:
        result = orchestrator.train_gating(
            conn_mock, retraining_id="r1", version_id="v1", config={"gating_training": {"enabled": False}}
        )

    assert result["ok"] is False
    assert result["reason"] == "gating_training_disabled"
    run_mock.assert_not_called()


# -- multitask (direction+magnitude+volatility) training stage ----------------


def test_train_multitask_invokes_script_with_version_id_flag():
    conn_mock, _ = _make_conn_mock()
    completed = MagicMock(returncode=0, stdout="ok", stderr="")

    with patch("retraining.orchestrator.subprocess.run", return_value=completed) as run_mock:
        result = orchestrator.train_multitask(conn_mock, retraining_id="r1", version_id="v1", config={})

    argv = run_mock.call_args.args[0]
    assert "train_multitask.py" in argv[1]
    assert "--version-id" in argv
    assert "v1" in argv
    assert result["ok"] is True


def test_train_multitask_subprocess_failure_does_not_reject_model_version():
    """Unlike train()'s hard failure path, a multitask-training subprocess
    failure must never reject the candidate model_version - multitask
    artifacts are optional (see retraining/artifacts.py's
    OPTIONAL_MULTITASK_FILES)."""
    conn_mock, _ = _make_conn_mock()
    completed = MagicMock(returncode=1, stdout="", stderr="multitask boom")

    with patch("retraining.orchestrator.subprocess.run", return_value=completed), patch(
        "retraining.orchestrator.update_retraining_event_status"
    ) as update_event_mock, patch("retraining.orchestrator.update_model_version_status") as update_version_mock:
        result = orchestrator.train_multitask(conn_mock, retraining_id="r1", version_id="v1", config={})

    assert result["ok"] is False
    update_version_mock.assert_not_called()
    update_event_mock.assert_called_once()
    assert update_event_mock.call_args.kwargs["status"] == "running"


def test_train_multitask_disabled_returns_early_without_subprocess():
    conn_mock, _ = _make_conn_mock()

    with patch("retraining.orchestrator.subprocess.run") as run_mock:
        result = orchestrator.train_multitask(
            conn_mock, retraining_id="r1", version_id="v1", config={"multitask_training": {"enabled": False}}
        )

    assert result["ok"] is False
    assert result["reason"] == "multitask_training_disabled"
    run_mock.assert_not_called()


# -- Phase 2 sequence-encoder training stage -----------------------------------


def test_train_sequence_invokes_script_with_version_id_flag():
    conn_mock, _ = _make_conn_mock()
    completed = MagicMock(returncode=0, stdout="ok", stderr="")

    with patch("retraining.orchestrator.subprocess.run", return_value=completed) as run_mock:
        result = orchestrator.train_sequence(conn_mock, retraining_id="r1", version_id="v1", config={})

    argv = run_mock.call_args.args[0]
    assert "train_sequence.py" in argv[1]
    assert "--version-id" in argv
    assert "v1" in argv
    assert result["ok"] is True


def test_train_sequence_subprocess_failure_does_not_reject_model_version():
    """Unlike train()'s hard failure path, a sequence-training subprocess
    failure must never reject the candidate model_version - sequence
    artifacts are optional (see retraining/artifacts.py's
    OPTIONAL_SEQUENCE_FILES)."""
    conn_mock, _ = _make_conn_mock()
    completed = MagicMock(returncode=1, stdout="", stderr="sequence boom")

    with patch("retraining.orchestrator.subprocess.run", return_value=completed), patch(
        "retraining.orchestrator.update_retraining_event_status"
    ) as update_event_mock, patch("retraining.orchestrator.update_model_version_status") as update_version_mock:
        result = orchestrator.train_sequence(conn_mock, retraining_id="r1", version_id="v1", config={})

    assert result["ok"] is False
    update_version_mock.assert_not_called()
    update_event_mock.assert_called_once()
    assert update_event_mock.call_args.kwargs["status"] == "running"


def test_train_sequence_disabled_returns_early_without_subprocess():
    conn_mock, _ = _make_conn_mock()

    with patch("retraining.orchestrator.subprocess.run") as run_mock:
        result = orchestrator.train_sequence(
            conn_mock, retraining_id="r1", version_id="v1", config={"sequence_training": {"enabled": False}}
        )

    assert result["ok"] is False
    assert result["reason"] == "sequence_training_disabled"
    run_mock.assert_not_called()


def test_commit_hashes_and_vault_add_include_topology_files_when_present(tmp_path):
    """Direct test for the spec requirement 'Aether-Vault commit includes
    topology artifacts when present': the candidate's whole version_dir is
    swept into `av add`, and compute_artifact_hashes() is called with
    ALL_TRACKED_FILES (required + optional topology filenames) so topology
    artifacts get hashed onto the model_versions row too."""
    from retraining.artifacts import ALL_TRACKED_FILES, OPTIONAL_TOPOLOGY_FILES

    conn_mock, _ = _make_conn_mock()
    root_dir = tmp_path
    version_dir = root_dir / "ml" / "versions" / "v1"
    version_dir.mkdir(parents=True)
    for filename in ALL_TRACKED_FILES:
        content = "{}" if filename.endswith(".json") else "data"
        (version_dir / filename).write_text(content, encoding="utf-8")

    vault_result = {"ok": True, "vault_commit": "abc123", "stage": "done", "steps": {}}

    with patch("retraining.orchestrator.ROOT_DIR", root_dir), patch(
        "retraining.orchestrator.candidate_dir", return_value=version_dir
    ), patch(
        "retraining.orchestrator.commit_candidate_to_vault", return_value=vault_result
    ) as vault_mock, patch(
        "retraining.orchestrator.update_model_version_status"
    ) as update_version_mock, patch("retraining.orchestrator.update_retraining_event_status"):
        result = orchestrator.commit(conn_mock, retraining_id="r1", version_id="v1", config={})

    assert result["ok"] is True

    add_paths = vault_mock.call_args.args[1]
    assert str(version_dir.relative_to(root_dir)) in add_paths

    hashes = update_version_mock.call_args.kwargs["artifact_hashes"]
    for filename in OPTIONAL_TOPOLOGY_FILES:
        assert filename in hashes
