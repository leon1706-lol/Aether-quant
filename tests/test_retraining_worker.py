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
        "retraining.worker.validate", return_value={"ok": True}
    ), patch("retraining.worker.backtest", return_value={"ok": True}), patch(
        "retraining.worker.commit", return_value={"ok": True, "vault_commit": "abc"}
    ), patch("retraining.worker.promote") as promote_mock, patch("retraining.worker.status", return_value={}):
        result = worker.run_once()

    train_topology_mock.assert_called_once()
    promote_mock.assert_not_called()
    assert result["reason"] == "validated_awaiting_manual_promotion"


def test_run_once_auto_promote_true_calls_promote():
    worker = _worker({"worker": {"auto_promote": True}})

    with patch("retraining.worker.plan", return_value={"should_plan": True, "retraining_id": "r1"}), patch(
        "retraining.worker.train", return_value={"ok": True, "version_id": "v1"}
    ), patch("retraining.worker.train_topology"), patch(
        "retraining.worker.validate", return_value={"ok": True}
    ), patch("retraining.worker.backtest", return_value={"ok": True}), patch(
        "retraining.worker.commit", return_value={"ok": True, "vault_commit": "abc"}
    ), patch("retraining.worker.promote", return_value={"ok": True, "version_id": "v1"}) as promote_mock, patch(
        "retraining.worker.status", return_value={}
    ):
        result = worker.run_once()

    promote_mock.assert_called_once()
    assert result["reason"] == "promoted"


def test_run_once_stops_when_validation_fails():
    worker = _worker()

    with patch("retraining.worker.plan", return_value={"should_plan": True, "retraining_id": "r1"}), patch(
        "retraining.worker.train", return_value={"ok": True, "version_id": "v1"}
    ), patch("retraining.worker.train_topology"), patch(
        "retraining.worker.validate", return_value={"ok": False}
    ), patch("retraining.worker.backtest") as backtest_mock:
        result = worker.run_once()

    backtest_mock.assert_not_called()
    assert result["reason"] == "validation_failed"


def test_run_once_calls_train_topology_between_train_and_validate():
    """V2-17.5: topology training must run after the primary train() stage
    succeeds and before validate() - and its own failure must not stop the
    primary candidate from proceeding to validate()."""
    worker = _worker()
    call_order = []

    with patch("retraining.worker.plan", return_value={"should_plan": True, "retraining_id": "r1"}), patch(
        "retraining.worker.train",
        side_effect=lambda *a, **k: call_order.append("train") or {"ok": True, "version_id": "v1"},
    ), patch(
        "retraining.worker.train_topology",
        side_effect=lambda *a, **k: call_order.append("train_topology") or {"ok": False, "error": "no data yet"},
    ) as train_topology_mock, patch(
        "retraining.worker.validate",
        side_effect=lambda *a, **k: call_order.append("validate") or {"ok": True},
    ), patch("retraining.worker.backtest", return_value={"ok": True}), patch(
        "retraining.worker.commit", return_value={"ok": True, "vault_commit": "abc"}
    ), patch("retraining.worker.promote"), patch("retraining.worker.status", return_value={}):
        result = worker.run_once()

    assert call_order == ["train", "train_topology", "validate"]
    train_topology_mock.assert_called_once_with(worker._conn, "r1", "v1", worker.config)
    # a failed/skipped topology training result must not block the primary
    # candidate's own pipeline.
    assert result["reason"] == "validated_awaiting_manual_promotion"
