"""Tests for retraining.worker — V2-17.

Conventions: no test classes, module-level helpers, _pg_conn constructor
injection mirroring performance.trigger_worker's TriggerWorker test style,
plus patching the orchestrator stage functions retraining.worker already
imported by name (patch retraining.worker.<name>, not
retraining.orchestrator.<name>).
"""

from unittest.mock import MagicMock, patch

from retraining.worker import RetrainingWorker


def _make_conn_mock():
    conn_mock = MagicMock()
    cur_mock = MagicMock()
    conn_mock.cursor.return_value.__enter__.return_value = cur_mock
    conn_mock.cursor.return_value.__exit__.return_value = False
    return conn_mock, cur_mock


def _worker(config_overrides=None):
    conn_mock, _ = _make_conn_mock()
    config = {"enabled": True, "worker": {"auto_promote": False}}
    if config_overrides:
        config.update(config_overrides)
    return RetrainingWorker(config=config, _pg_conn=conn_mock)


def test_run_once_no_ops_when_disabled():
    worker = _worker({"enabled": False})

    with patch("retraining.worker.plan") as plan_mock:
        result = worker.run_once()

    plan_mock.assert_not_called()
    assert result == {"ran": False, "reason": "disabled"}


def test_run_once_stops_when_plan_says_no():
    worker = _worker()

    with patch("retraining.worker.plan", return_value={"should_plan": False, "reason": "cooldown_active"}) as plan_mock, patch(
        "retraining.worker.train"
    ) as train_mock:
        result = worker.run_once()

    plan_mock.assert_called_once()
    train_mock.assert_not_called()
    assert result == {"ran": False, "reason": "cooldown_active"}


def test_run_once_stops_when_train_fails():
    worker = _worker()

    with patch("retraining.worker.plan", return_value={"should_plan": True, "retraining_id": "r1"}), patch(
        "retraining.worker.train", return_value={"ok": False, "version_id": "v1"}
    ), patch("retraining.worker.validate") as validate_mock:
        result = worker.run_once()

    validate_mock.assert_not_called()
    assert result["reason"] == "train_failed"


def test_run_once_auto_promote_false_stops_after_commit():
    worker = _worker({"worker": {"auto_promote": False}})

    with patch("retraining.worker.plan", return_value={"should_plan": True, "retraining_id": "r1"}), patch(
        "retraining.worker.train", return_value={"ok": True, "version_id": "v1"}
    ), patch("retraining.worker.train_topology") as train_topology_mock, patch(
        "retraining.worker.train_gating"
    ) as train_gating_mock, patch("retraining.worker.train_multitask"), patch(
        "retraining.worker.train_sequence"
    ), patch(
        "retraining.worker.train_strategy_selector"
    ), patch(
        "retraining.worker.validate", return_value={"ok": True}
    ), patch("retraining.worker.backtest", return_value={"ok": True}), patch(
        "retraining.worker.commit", return_value={"ok": True, "vault_commit": "abc"}
    ), patch("retraining.worker.promote") as promote_mock, patch("retraining.worker.status", return_value={}):
        result = worker.run_once()

    train_topology_mock.assert_called_once()
    train_gating_mock.assert_called_once()
    promote_mock.assert_not_called()
    assert result["reason"] == "validated_awaiting_manual_promotion"


def test_run_once_auto_promote_true_calls_promote():
    worker = _worker({"worker": {"auto_promote": True}})

    with patch("retraining.worker.plan", return_value={"should_plan": True, "retraining_id": "r1"}), patch(
        "retraining.worker.train", return_value={"ok": True, "version_id": "v1"}
    ), patch("retraining.worker.train_topology"), patch("retraining.worker.train_gating"), patch(
        "retraining.worker.train_multitask"
    ), patch("retraining.worker.train_sequence"), patch(
        "retraining.worker.train_strategy_selector"
    ), patch(
        "retraining.worker.validate", return_value={"ok": True}
    ), patch("retraining.worker.backtest", return_value={"ok": True}), patch(
        "retraining.worker.commit", return_value={"ok": True, "vault_commit": "abc"}
    ), patch("retraining.worker.promote", return_value={"ok": True, "version_id": "v1"}) as promote_mock, patch(
        "retraining.worker.status", return_value={}
    ):
        result = worker.run_once()

    promote_mock.assert_called_once()
    assert result["reason"] == "promoted"


def test_run_once_auto_promote_forced_off_when_runtime_mode_is_live():
    """V2-22 safety net: even with auto_promote=True, a live runtime mode
    must force manual promotion - a model change should never silently go
    live without a human looking at it once real orders are possible."""
    worker = _worker({"worker": {"auto_promote": True, "auto_promote_blocked_in_live_mode": True}})

    with patch("retraining.worker.plan", return_value={"should_plan": True, "retraining_id": "r1"}), patch(
        "retraining.worker.train", return_value={"ok": True, "version_id": "v1"}
    ), patch("retraining.worker.train_topology"), patch("retraining.worker.train_gating"), patch(
        "retraining.worker.train_multitask"
    ), patch("retraining.worker.train_sequence"), patch(
        "retraining.worker.train_strategy_selector"
    ), patch(
        "retraining.worker.validate", return_value={"ok": True}
    ), patch("retraining.worker.backtest", return_value={"ok": True}), patch(
        "retraining.worker.commit", return_value={"ok": True, "vault_commit": "abc"}
    ), patch("retraining.worker.promote") as promote_mock, patch(
        "retraining.worker.status", return_value={}
    ), patch("retraining.worker.read_runtime_mode", return_value="live"):
        result = worker.run_once()

    promote_mock.assert_not_called()
    assert result["reason"] == "validated_awaiting_manual_promotion"


def test_run_once_auto_promote_proceeds_when_runtime_mode_is_not_live():
    worker = _worker({"worker": {"auto_promote": True, "auto_promote_blocked_in_live_mode": True}})

    with patch("retraining.worker.plan", return_value={"should_plan": True, "retraining_id": "r1"}), patch(
        "retraining.worker.train", return_value={"ok": True, "version_id": "v1"}
    ), patch("retraining.worker.train_topology"), patch("retraining.worker.train_gating"), patch(
        "retraining.worker.train_multitask"
    ), patch("retraining.worker.train_sequence"), patch(
        "retraining.worker.train_strategy_selector"
    ), patch(
        "retraining.worker.validate", return_value={"ok": True}
    ), patch("retraining.worker.backtest", return_value={"ok": True}), patch(
        "retraining.worker.commit", return_value={"ok": True, "vault_commit": "abc"}
    ), patch("retraining.worker.promote", return_value={"ok": True, "version_id": "v1"}) as promote_mock, patch(
        "retraining.worker.status", return_value={}
    ), patch("retraining.worker.read_runtime_mode", return_value="observation"):
        result = worker.run_once()

    promote_mock.assert_called_once()
    assert result["reason"] == "promoted"


def test_run_once_auto_promote_ignores_live_mode_when_guard_disabled():
    worker = _worker({"worker": {"auto_promote": True, "auto_promote_blocked_in_live_mode": False}})

    with patch("retraining.worker.plan", return_value={"should_plan": True, "retraining_id": "r1"}), patch(
        "retraining.worker.train", return_value={"ok": True, "version_id": "v1"}
    ), patch("retraining.worker.train_topology"), patch("retraining.worker.train_gating"), patch(
        "retraining.worker.train_multitask"
    ), patch("retraining.worker.train_sequence"), patch(
        "retraining.worker.train_strategy_selector"
    ), patch(
        "retraining.worker.validate", return_value={"ok": True}
    ), patch("retraining.worker.backtest", return_value={"ok": True}), patch(
        "retraining.worker.commit", return_value={"ok": True, "vault_commit": "abc"}
    ), patch("retraining.worker.promote", return_value={"ok": True, "version_id": "v1"}) as promote_mock, patch(
        "retraining.worker.status", return_value={}
    ), patch("retraining.worker.read_runtime_mode", return_value="live"):
        result = worker.run_once()

    promote_mock.assert_called_once()
    assert result["reason"] == "promoted"


def test_run_once_stops_when_validation_fails():
    worker = _worker()

    with patch("retraining.worker.plan", return_value={"should_plan": True, "retraining_id": "r1"}), patch(
        "retraining.worker.train", return_value={"ok": True, "version_id": "v1"}
    ), patch("retraining.worker.train_topology"), patch("retraining.worker.train_gating"), patch(
        "retraining.worker.train_multitask"
    ), patch("retraining.worker.train_sequence"), patch(
        "retraining.worker.train_strategy_selector"
    ), patch(
        "retraining.worker.validate", return_value={"ok": False}
    ), patch("retraining.worker.backtest") as backtest_mock:
        result = worker.run_once()

    backtest_mock.assert_not_called()
    assert result["reason"] == "validation_failed"


def test_run_once_calls_train_topology_then_train_gating_between_train_and_validate():
    """V2-17.5 + learned-gating: both best-effort trainers must run after
    the primary train() stage succeeds and before validate(), topology
    first then gating - and either one's failure must not stop the primary
    candidate from proceeding to validate()."""
    worker = _worker()
    call_order = []

    with patch("retraining.worker.plan", return_value={"should_plan": True, "retraining_id": "r1"}), patch(
        "retraining.worker.train",
        side_effect=lambda *a, **k: call_order.append("train") or {"ok": True, "version_id": "v1"},
    ), patch(
        "retraining.worker.train_topology",
        side_effect=lambda *a, **k: call_order.append("train_topology") or {"ok": False, "error": "no data yet"},
    ) as train_topology_mock, patch(
        "retraining.worker.train_gating",
        side_effect=lambda *a, **k: call_order.append("train_gating") or {"ok": False, "error": "no data yet"},
    ) as train_gating_mock, patch("retraining.worker.train_multitask"), patch(
        "retraining.worker.train_sequence"
    ), patch(
        "retraining.worker.train_strategy_selector"
    ), patch(
        "retraining.worker.validate",
        side_effect=lambda *a, **k: call_order.append("validate") or {"ok": True},
    ), patch("retraining.worker.backtest", return_value={"ok": True}), patch(
        "retraining.worker.commit", return_value={"ok": True, "vault_commit": "abc"}
    ), patch("retraining.worker.promote"), patch("retraining.worker.status", return_value={}):
        result = worker.run_once()

    assert call_order == ["train", "train_topology", "train_gating", "validate"]
    train_topology_mock.assert_called_once_with(worker._conn, "r1", "v1", worker.config)
    train_gating_mock.assert_called_once_with(worker._conn, "r1", "v1", worker.config)
    # a failed/skipped topology or gating training result must not block
    # the primary candidate's own pipeline.
    assert result["reason"] == "validated_awaiting_manual_promotion"


def test_init_reconciles_stale_running_events_before_entering_run_loop():
    """#48: a retraining_events row orphaned by a prior crash/redeploy must be
    reconciled at worker startup, before run()'s poll loop begins - otherwise
    it silently blocks every future retraining attempt for the full cooldown
    window. Patches retraining.worker.reconcile_stale_running_events (the name
    RetrainingWorker.__init__ actually calls), matching this file's own
    patch-by-import-site convention."""
    conn_mock, _ = _make_conn_mock()
    config = {"enabled": True, "worker": {"auto_promote": False}}

    with patch("retraining.worker.reconcile_stale_running_events", return_value=["orphaned-1"]) as reconcile_mock:
        worker = RetrainingWorker(config=config, _pg_conn=conn_mock)

    reconcile_mock.assert_called_once_with(conn_mock, config)
    assert worker.config is config


# ---------------------------------------------------------------------------
# Auto-rollback (V5.1 Phase 6, production safety)
# ---------------------------------------------------------------------------


def test_live_degradation_signals_all_false_when_nothing_present(tmp_path):
    worker = _worker()
    missing_state_path = tmp_path / "state.json"

    with patch("retraining.worker._STATE_PATH", missing_state_path), patch(
        "retraining.worker.fetch_triggers_since", return_value=[]
    ):
        signals = worker._live_degradation_signals()

    assert signals == {"kill_switch_tripped": False, "net_sharpe_decay": False, "rank_ic_decay": False}


def test_live_degradation_signals_reads_kill_switch_tripped_from_state_json(tmp_path):
    worker = _worker()
    state_path = tmp_path / "state.json"
    state_path.write_text('{"kill_switch": {"tripped": true}}', encoding="utf-8")

    with patch("retraining.worker._STATE_PATH", state_path), patch(
        "retraining.worker.fetch_triggers_since", return_value=[]
    ):
        signals = worker._live_degradation_signals()

    assert signals["kill_switch_tripped"] is True


def test_live_degradation_signals_maps_trigger_types_to_abstract_names(tmp_path):
    worker = _worker()
    missing_state_path = tmp_path / "state.json"
    triggers = [{"trigger_type": "sharpe_degradation_trigger"}, {"trigger_type": "rank_ic_decay_trigger"}]

    with patch("retraining.worker._STATE_PATH", missing_state_path), patch(
        "retraining.worker.fetch_triggers_since", return_value=triggers
    ):
        signals = worker._live_degradation_signals()

    assert signals["net_sharpe_decay"] is True
    assert signals["rank_ic_decay"] is True


def test_live_degradation_signals_never_raises_on_malformed_state_file(tmp_path):
    worker = _worker()
    state_path = tmp_path / "state.json"
    state_path.write_text("not valid json", encoding="utf-8")

    with patch("retraining.worker._STATE_PATH", state_path), patch(
        "retraining.worker.fetch_triggers_since", side_effect=Exception("db down")
    ):
        signals = worker._live_degradation_signals()

    assert signals == {"kill_switch_tripped": False, "net_sharpe_decay": False, "rank_ic_decay": False}


def test_check_auto_rollback_no_ops_when_selector_says_no():
    worker = _worker({"auto_rollback": {"enabled": False}})
    decision = {"should_rollback": False, "to_version_id": None, "reason": "auto_rollback_disabled", "failures": []}
    status_result = {"active_version_id": "v1", "degradation_signals": {}, "decision": decision}

    with patch("retraining.worker.RetrainingWorker._live_degradation_signals", return_value={}), patch(
        "retraining.worker.auto_rollback_status", return_value=status_result
    ) as status_mock, patch("retraining.worker.rollback") as rollback_mock, patch(
        "retraining.worker.insert_triggers"
    ) as insert_mock:
        result = worker.check_auto_rollback()

    status_mock.assert_called_once()
    rollback_mock.assert_not_called()
    insert_mock.assert_not_called()
    assert result == status_result


def test_check_auto_rollback_calls_rollback_and_notifies_when_selector_says_yes():
    worker = _worker({"auto_rollback": {"enabled": True}})
    decision = {"should_rollback": True, "to_version_id": "v_old", "reason": "kill_switch_tripped", "failures": []}
    status_result = {"active_version_id": "v_new", "degradation_signals": {"kill_switch_tripped": True}, "decision": decision}
    rollback_result = {"ok": True, "restored_version_id": "v_old"}

    with patch(
        "retraining.worker.RetrainingWorker._live_degradation_signals", return_value={"kill_switch_tripped": True}
    ), patch("retraining.worker.auto_rollback_status", return_value=status_result), patch(
        "retraining.worker.rollback", return_value=rollback_result
    ) as rollback_mock, patch("retraining.worker.insert_triggers", return_value=1) as insert_mock:
        result = worker.check_auto_rollback()

    rollback_mock.assert_called_once_with(worker._conn, "v_old", worker.config)
    insert_mock.assert_called_once()
    inserted_trigger = insert_mock.call_args.args[1][0]
    assert inserted_trigger["trigger_type"] == "auto_rollback_triggered"
    assert "v_old" in inserted_trigger["recommended_action"]
    assert result["rollback_result"] == rollback_result


def test_check_auto_rollback_notifies_even_when_rollback_itself_fails():
    worker = _worker({"auto_rollback": {"enabled": True}})
    decision = {"should_rollback": True, "to_version_id": "v_old", "reason": "kill_switch_tripped", "failures": []}
    status_result = {"active_version_id": "v_new", "degradation_signals": {}, "decision": decision}
    rollback_result = {"ok": False, "error": "artifact_hash_mismatch"}

    with patch("retraining.worker.RetrainingWorker._live_degradation_signals", return_value={}), patch(
        "retraining.worker.auto_rollback_status", return_value=status_result
    ), patch("retraining.worker.rollback", return_value=rollback_result), patch(
        "retraining.worker.insert_triggers", return_value=1
    ) as insert_mock:
        result = worker.check_auto_rollback()

    insert_mock.assert_called_once()
    inserted_trigger = insert_mock.call_args.args[1][0]
    assert "FAILED" in inserted_trigger["recommended_action"]
    assert result["rollback_result"]["ok"] is False


def test_notify_auto_rollback_never_raises_on_insert_failure():
    worker = _worker()
    decision = {"should_rollback": True, "to_version_id": "v_old", "reason": "kill_switch_tripped"}
    rollback_result = {"ok": True}

    with patch("retraining.worker.insert_triggers", side_effect=Exception("db down")):
        worker._notify_auto_rollback(decision, rollback_result)  # must not raise


def test_run_loop_calls_check_auto_rollback_alongside_run_once():
    """run() must call check_auto_rollback() on the SAME poll cadence as
    run_once(), as a genuinely separate concern (active-model health, not
    new-candidate promotion) - not nested inside run_once()."""
    worker = _worker()

    def _stop_after_one_cycle(*args, **kwargs):
        raise KeyboardInterrupt()

    with patch("retraining.worker.RetrainingWorker.run_once", return_value={"ran": False, "reason": "disabled"}), patch(
        "retraining.worker.RetrainingWorker.check_auto_rollback",
        return_value={"decision": {"should_rollback": False}},
    ) as check_mock, patch("retraining.worker.time.sleep", side_effect=_stop_after_one_cycle):
        worker.run()

    check_mock.assert_called_once()
