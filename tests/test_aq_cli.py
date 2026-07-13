"""Tests for aq_cli.py — the `aq` convenience CLI.

Conventions: no test classes, module-level helpers. Subprocess-wrapping
commands are tested by mocking aq_cli._run (the single choke point every
subprocess-based subcommand funnels through) and asserting the exact argv
built - never actually shelling out. trade-lock is tested via its own real
logic (risk.manual_override), same as tests/test_manual_override.py. fetch
is the second in-process exception (calls data_pipeline.fetch directly, no
subprocess) - tested here as wiring-only, with aq_cli.fetch_adhoc_asset
patched; its real logic (yfinance never touched, correct Lean paths,
config.json read-modify-write) is covered by tests/test_fetch.py instead.

`cmd_test` is the one exception to the `_run` choke point: it needs
captured (not just streamed) output to parse the pass/fail count for the
README badge, so it funnels through `_run_captured` instead - tests for it
must mock that function specifically, never `_run` (which `cmd_test` no
longer calls at all). Mocking the wrong one doesn't fail loudly - it lets a
real, full recursive `pytest tests/` subprocess run instead, which is
exactly the bug this comment exists to prevent from being reintroduced.
"""

import json
import sys
from datetime import date
from unittest.mock import MagicMock, patch

import aq_cli


def _parse_and_dispatch(argv: list[str], run_mock: MagicMock) -> int:
    parser = aq_cli.build_parser()
    args = parser.parse_args(argv)
    with patch("aq_cli._run", run_mock):
        return args.func(args)


def test_train_wraps_plain_train_py():
    run_mock = MagicMock(return_value=0)
    _parse_and_dispatch(["train"], run_mock)

    assert run_mock.call_args.args[0] == [sys.executable, "train.py"]


def test_train_dataset_only_flag():
    run_mock = MagicMock(return_value=0)
    _parse_and_dispatch(["train", "--dataset-only"], run_mock)

    assert run_mock.call_args.args[0] == [sys.executable, "train.py", "--dataset-only"]


def test_train_walk_forward_flag():
    run_mock = MagicMock(return_value=0)
    _parse_and_dispatch(["train", "--walk-forward"], run_mock)

    assert run_mock.call_args.args[0] == [sys.executable, "train.py", "--walk-forward"]


def test_train_walk_forward_passes_through_step_days_and_mode():
    run_mock = MagicMock(return_value=0)
    _parse_and_dispatch(["train", "--walk-forward", "--step-days", "90", "--mode", "rolling"], run_mock)

    assert run_mock.call_args.args[0] == [
        sys.executable,
        "train.py",
        "--walk-forward",
        "--step-days",
        "90",
        "--mode",
        "rolling",
    ]


def test_train_walk_forward_is_mutually_exclusive_with_dataset_only():
    parser = aq_cli.build_parser()
    try:
        parser.parse_args(["train", "--walk-forward", "--dataset-only"])
        assert False, "expected SystemExit from argparse mutual exclusion"
    except SystemExit:
        pass


def test_train_flags_are_mutually_exclusive():
    parser = aq_cli.build_parser()
    try:
        parser.parse_args(["train", "--dataset-only", "--init-only"])
        assert False, "expected SystemExit from argparse mutual exclusion"
    except SystemExit:
        pass


def test_train_gating_only_invokes_train_gating_py_with_generated_version_id():
    # --gating-only doesn't funnel through the plain train.py argv-building
    # path - it shells out to train_gating.py separately (see
    # aq_cli._train_gating_only), so it's tested on its own rather than via
    # _parse_and_dispatch's simple argv assertion.
    run_mock = MagicMock(return_value=0)
    parser = aq_cli.build_parser()
    args = parser.parse_args(["train", "--gating-only"])

    with patch("aq_cli._run", run_mock), patch("aq_cli.uuid.uuid4", return_value="fixed-uuid"), patch(
        "pathlib.Path.exists", return_value=True
    ), patch("shutil.copy2") as copy_mock:
        exit_code = args.func(args)

    assert exit_code == 0
    argv = run_mock.call_args.args[0]
    assert argv[:2] == [sys.executable, "train_gating.py"]
    assert argv[2:] == ["--version-id", "gating-only-fixed-uuid"]
    assert copy_mock.call_count == 3


def test_train_gating_only_propagates_trainer_failure_without_copying():
    run_mock = MagicMock(return_value=1)
    parser = aq_cli.build_parser()
    args = parser.parse_args(["train", "--gating-only"])

    with patch("aq_cli._run", run_mock), patch("shutil.copy2") as copy_mock:
        exit_code = args.func(args)

    assert exit_code == 1
    copy_mock.assert_not_called()


def test_train_gating_only_leaves_active_ml_unchanged_when_trainer_skips_artifacts():
    # train_gating.py exits 0 (not an error) when there isn't enough
    # validation/backtest data yet, and simply doesn't write artifacts -
    # aq must treat that as a no-op, not copy partial/missing files.
    run_mock = MagicMock(return_value=0)
    parser = aq_cli.build_parser()
    args = parser.parse_args(["train", "--gating-only"])

    with patch("aq_cli._run", run_mock), patch("pathlib.Path.exists", return_value=False), patch(
        "shutil.copy2"
    ) as copy_mock:
        exit_code = args.func(args)

    assert exit_code == 0
    copy_mock.assert_not_called()


def test_train_multitask_only_invokes_train_multitask_py_with_generated_version_id():
    # --multitask-only mirrors --gating-only exactly (see
    # aq_cli._train_multitask_only) - shells out to train_multitask.py
    # separately, tested on its own rather than via _parse_and_dispatch.
    run_mock = MagicMock(return_value=0)
    parser = aq_cli.build_parser()
    args = parser.parse_args(["train", "--multitask-only"])

    with patch("aq_cli._run", run_mock), patch("aq_cli.uuid.uuid4", return_value="fixed-uuid"), patch(
        "pathlib.Path.exists", return_value=True
    ), patch("shutil.copy2") as copy_mock:
        exit_code = args.func(args)

    assert exit_code == 0
    argv = run_mock.call_args.args[0]
    assert argv[:2] == [sys.executable, "train_multitask.py"]
    assert argv[2:] == ["--version-id", "multitask-only-fixed-uuid"]
    assert copy_mock.call_count == 3


def test_train_multitask_only_propagates_trainer_failure_without_copying():
    run_mock = MagicMock(return_value=1)
    parser = aq_cli.build_parser()
    args = parser.parse_args(["train", "--multitask-only"])

    with patch("aq_cli._run", run_mock), patch("shutil.copy2") as copy_mock:
        exit_code = args.func(args)

    assert exit_code == 1
    copy_mock.assert_not_called()


def test_train_multitask_only_leaves_active_ml_unchanged_when_trainer_skips_artifacts():
    # train_multitask.py exits 0 (not an error) when there isn't enough
    # train/validation/backtest data yet, and simply doesn't write
    # artifacts - aq must treat that as a no-op, not copy partial files.
    run_mock = MagicMock(return_value=0)
    parser = aq_cli.build_parser()
    args = parser.parse_args(["train", "--multitask-only"])

    with patch("aq_cli._run", run_mock), patch("pathlib.Path.exists", return_value=False), patch(
        "shutil.copy2"
    ) as copy_mock:
        exit_code = args.func(args)

    assert exit_code == 0
    copy_mock.assert_not_called()


def test_train_sequence_only_invokes_train_sequence_py_with_generated_version_id():
    # --sequence-only mirrors --multitask-only/--gating-only exactly (see
    # aq_cli._train_sequence_only) - shells out to train_sequence.py
    # separately, tested on its own rather than via _parse_and_dispatch.
    run_mock = MagicMock(return_value=0)
    parser = aq_cli.build_parser()
    args = parser.parse_args(["train", "--sequence-only"])

    with patch("aq_cli._run", run_mock), patch("aq_cli.uuid.uuid4", return_value="fixed-uuid"), patch(
        "pathlib.Path.exists", return_value=True
    ), patch("shutil.copy2") as copy_mock:
        exit_code = args.func(args)

    assert exit_code == 0
    argv = run_mock.call_args.args[0]
    assert argv[:2] == [sys.executable, "train_sequence.py"]
    assert argv[2:] == ["--version-id", "sequence-only-fixed-uuid"]
    assert copy_mock.call_count == 3


def test_train_sequence_only_propagates_trainer_failure_without_copying():
    run_mock = MagicMock(return_value=1)
    parser = aq_cli.build_parser()
    args = parser.parse_args(["train", "--sequence-only"])

    with patch("aq_cli._run", run_mock), patch("shutil.copy2") as copy_mock:
        exit_code = args.func(args)

    assert exit_code == 1
    copy_mock.assert_not_called()


def test_train_sequence_only_leaves_active_ml_unchanged_when_trainer_skips_artifacts():
    run_mock = MagicMock(return_value=0)
    parser = aq_cli.build_parser()
    args = parser.parse_args(["train", "--sequence-only"])

    with patch("aq_cli._run", run_mock), patch("pathlib.Path.exists", return_value=False), patch(
        "shutil.copy2"
    ) as copy_mock:
        exit_code = args.func(args)

    assert exit_code == 0
    copy_mock.assert_not_called()


def test_test_wraps_pytest_tests_dir():
    # Deliberately NOT using _parse_and_dispatch: cmd_test funnels through
    # _run_captured, not _run - see this file's module docstring. Also mocks
    # _update_readme_test_badge - otherwise this "unit" test would write a
    # fake pass count into the repo's real README.md as a side effect.
    captured_mock = MagicMock(return_value=(0, "5 passed in 0.42s"))
    parser = aq_cli.build_parser()
    args = parser.parse_args(["test"])
    with patch("aq_cli._run_captured", captured_mock), patch("aq_cli._update_readme_test_badge"):
        args.func(args)

    assert captured_mock.call_args.args[0] == [sys.executable, "-m", "pytest", "tests/", "--color=yes"]


def test_test_never_calls_run_or_a_real_subprocess():
    """Regression guard: mocking only aq_cli._run must NOT let cmd_test fall
    through to a real subprocess call - that gap previously caused every
    full test-suite run to recursively spawn another full, real `pytest
    tests/` subprocess via this exact test."""
    run_mock = MagicMock(return_value=0)
    popen_mock = MagicMock()
    parser = aq_cli.build_parser()
    args = parser.parse_args(["test"])
    with patch("aq_cli._run", run_mock), patch("aq_cli.subprocess.Popen", popen_mock), patch(
        "aq_cli._run_captured", MagicMock(return_value=(0, "1 passed"))
    ), patch("aq_cli._update_readme_test_badge"):
        args.func(args)

    run_mock.assert_not_called()
    popen_mock.assert_not_called()


def test_backtest_wraps_lean_backtest_dot():
    run_mock = MagicMock(return_value=0)
    with patch("aq_cli._find_quantconnect_lean_binary", return_value="lean"), patch(
        "generate_backtest_report.update_readme_from_latest_backtest", return_value=False
    ):
        _parse_and_dispatch(["backtest"], run_mock)

    assert run_mock.call_args.args[0] == ["lean", "backtest", "."]


def test_backtest_updates_readme_on_success():
    run_mock = MagicMock(return_value=0)
    report_mock = MagicMock(return_value=True)
    with patch("aq_cli._find_quantconnect_lean_binary", return_value="lean"), patch(
        "generate_backtest_report.update_readme_from_latest_backtest", report_mock
    ):
        _parse_and_dispatch(["backtest"], run_mock)

    report_mock.assert_called_once()


def test_backtest_skips_readme_update_when_lean_backtest_fails():
    run_mock = MagicMock(return_value=1)
    report_mock = MagicMock(return_value=True)
    with patch("aq_cli._find_quantconnect_lean_binary", return_value="lean"), patch(
        "generate_backtest_report.update_readme_from_latest_backtest", report_mock
    ):
        exit_code = _parse_and_dispatch(["backtest"], run_mock)

    report_mock.assert_not_called()
    assert exit_code == 1


def test_backtest_never_fails_when_report_generation_raises():
    run_mock = MagicMock(return_value=0)
    with patch("aq_cli._find_quantconnect_lean_binary", return_value="lean"), patch(
        "generate_backtest_report.update_readme_from_latest_backtest", side_effect=RuntimeError("boom")
    ):
        exit_code = _parse_and_dispatch(["backtest"], run_mock)

    assert exit_code == 0


def test_backtest_errors_cleanly_when_lean_not_found(capsys):
    parser = aq_cli.build_parser()
    args = parser.parse_args(["backtest"])
    with patch("aq_cli._find_quantconnect_lean_binary", return_value=None):
        result = args.func(args)

    assert result == 1
    assert "not found" in capsys.readouterr().err


def test_report_builds_expected_lean_report_command():
    run_mock = MagicMock(return_value=0)
    with patch("aq_cli._find_quantconnect_lean_binary", return_value="lean"):
        _parse_and_dispatch(["report", "2026-07-04_13-06-51", "1366365999"], run_mock)

    argv = run_mock.call_args.args[0]
    assert argv[0:2] == ["lean", "report"]
    assert "--backtest-results" in argv
    assert str(argv[argv.index("--backtest-results") + 1]).endswith("1366365999.json")
    assert "--overwrite" in argv


def test_api_wraps_uvicorn_on_port_8001():
    run_mock = MagicMock(return_value=0)
    _parse_and_dispatch(["api"], run_mock)

    argv = run_mock.call_args.args[0]
    assert argv == [sys.executable, "-m", "uvicorn", "monitoring.api_server:app", "--port", "8001", "--reload"]


def test_webui_runs_npm_run_dev_in_webui_dir():
    run_mock = MagicMock(return_value=0)
    _parse_and_dispatch(["webui"], run_mock)

    args, kwargs = run_mock.call_args
    assert args[0][-2:] == ["run", "dev"]


def test_docker_up_default_starts_redis_and_postgres():
    run_mock = MagicMock(return_value=0)
    _parse_and_dispatch(["docker", "up"], run_mock)

    assert run_mock.call_args.args[0] == ["docker", "compose", "up", "-d", "redis", "postgres"]


def test_docker_up_lean_uses_profile():
    run_mock = MagicMock(return_value=0)
    _parse_and_dispatch(["docker", "up", "--lean"], run_mock)

    assert run_mock.call_args.args[0] == ["docker", "compose", "--profile", "lean", "up", "-d"]


def test_docker_up_all_includes_every_worker():
    run_mock = MagicMock(return_value=0)
    _parse_and_dispatch(["docker", "up", "--all"], run_mock)

    argv = run_mock.call_args.args[0]
    for service in ("redis", "postgres", "aether-quant", "experience-worker", "performance-trigger-worker", "retraining-worker", "telegram-worker"):
        assert service in argv


def test_docker_build_wraps_compose_build():
    run_mock = MagicMock(return_value=0)
    _parse_and_dispatch(["docker", "build"], run_mock)

    assert run_mock.call_args.args[0] == ["docker", "compose", "build", "aether-quant"]


def test_paper_readiness_wraps_the_report_module():
    run_mock = MagicMock(return_value=0)
    _parse_and_dispatch(["paper-readiness"], run_mock)

    assert run_mock.call_args.args[0] == [sys.executable, "-m", "execution.paper_readiness_report"]


def test_retrain_dispatches_stage_and_forwards_extra_args():
    run_mock = MagicMock(return_value=0)
    _parse_and_dispatch(["retrain", "promote", "--version-id", "abc-123"], run_mock)

    assert run_mock.call_args.args[0] == [
        sys.executable,
        "-m",
        "retraining.orchestrator",
        "promote",
        "--version-id",
        "abc-123",
    ]


def test_retrain_rejects_unknown_stage():
    parser = aq_cli.build_parser()
    try:
        parser.parse_args(["retrain", "not_a_real_stage"])
        assert False, "expected SystemExit for an invalid stage choice"
    except SystemExit:
        pass


def test_status_wraps_git_status():
    run_mock = MagicMock(return_value=0)
    _parse_and_dispatch(["status"], run_mock)

    assert run_mock.call_args.args[0] == ["git", "status"]


def test_trade_lock_on_writes_true(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text('{"phase_v2": {"risk": {}}}', encoding="utf-8")

    parser = aq_cli.build_parser()
    args = parser.parse_args(["trade-lock", "--on"])
    with patch("aq_cli.CONFIG_PATH", config_path):
        args.func(args)

    from risk.manual_override import read_manual_trade_lock_override

    assert read_manual_trade_lock_override(config_path) is True


def test_trade_lock_off_writes_false(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text('{"phase_v2": {"risk": {"manual_trade_lock_override": true}}}', encoding="utf-8")

    parser = aq_cli.build_parser()
    args = parser.parse_args(["trade-lock", "--off"])
    with patch("aq_cli.CONFIG_PATH", config_path):
        args.func(args)

    from risk.manual_override import read_manual_trade_lock_override

    assert read_manual_trade_lock_override(config_path) is False


def test_trade_lock_auto_clears_override(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text('{"phase_v2": {"risk": {"manual_trade_lock_override": true}}}', encoding="utf-8")

    parser = aq_cli.build_parser()
    args = parser.parse_args(["trade-lock", "--auto"])
    with patch("aq_cli.CONFIG_PATH", config_path):
        args.func(args)

    from risk.manual_override import read_manual_trade_lock_override

    assert read_manual_trade_lock_override(config_path) is None


def test_trade_lock_status_prints_current_state(tmp_path, capsys):
    config_path = tmp_path / "config.json"
    config_path.write_text('{"phase_v2": {"risk": {"manual_trade_lock_override": false}}}', encoding="utf-8")

    parser = aq_cli.build_parser()
    args = parser.parse_args(["trade-lock", "--status"])
    with patch("aq_cli.CONFIG_PATH", config_path):
        args.func(args)

    assert "OFF" in capsys.readouterr().out


def test_trade_lock_requires_exactly_one_flag():
    parser = aq_cli.build_parser()
    try:
        parser.parse_args(["trade-lock"])
        assert False, "expected SystemExit when no trade-lock flag is given"
    except SystemExit:
        pass


# --- fetch ------------------------------------------------------------------


def _sample_fetch_report(**overrides) -> dict:
    report = {
        "ticker": "DOGEUSD",
        "asset_class": "crypto",
        "yahoo_symbol": "DOGE-USD",
        "data_path": "/tmp/dogeusd_trade.zip",
        "action": "dry_run",
        "rows_fetched": 3,
        "suggested_available_from": "2023-01-01",
        "suggested_available_to": "2023-01-03",
        "config_status": "not_attempted",
    }
    report.update(overrides)
    return report


def test_fetch_dispatches_to_fetch_adhoc_asset_with_parsed_args():
    fetch_mock = MagicMock(return_value=_sample_fetch_report())
    parser = aq_cli.build_parser()
    args = parser.parse_args(["fetch", "crypto", "--ticker", "DOGEUSD", "--start", "2023-01-01", "--end", "2023-01-03"])
    with patch("aq_cli.fetch_adhoc_asset", fetch_mock):
        exit_code = args.func(args)

    fetch_mock.assert_called_once_with("crypto", "DOGEUSD", "2023-01-01", "2023-01-03", apply=False, extra_metadata=None)
    assert exit_code == 0


def test_fetch_apply_flag_is_forwarded():
    fetch_mock = MagicMock(return_value=_sample_fetch_report(action="written", config_status="added"))
    parser = aq_cli.build_parser()
    args = parser.parse_args(
        ["fetch", "crypto", "--ticker", "DOGEUSD", "--start", "2023-01-01", "--end", "2023-01-03", "--apply"]
    )
    with patch("aq_cli.fetch_adhoc_asset", fetch_mock):
        args.func(args)

    fetch_mock.assert_called_once_with("crypto", "DOGEUSD", "2023-01-01", "2023-01-03", apply=True, extra_metadata=None)


def test_fetch_rejects_unsupported_asset_class():
    parser = aq_cli.build_parser()
    try:
        parser.parse_args(["fetch", "derivative", "--ticker", "X", "--start", "2020-01-01", "--end", "2020-02-01"])
        assert False, "expected SystemExit - 'derivative' not supported until V3"
    except SystemExit:
        pass


def test_fetch_rejects_non_iso_dates():
    parser = aq_cli.build_parser()
    try:
        parser.parse_args(["fetch", "stock", "--ticker", "AAPL", "--start", "02.02.2017", "--end", "2018-01-01"])
        assert False, "expected SystemExit for a non-ISO-8601 date"
    except SystemExit:
        pass


def test_fetch_returns_nonzero_when_no_data_returned():
    fetch_mock = MagicMock(return_value=_sample_fetch_report(action="no_data_returned", rows_fetched=0))
    parser = aq_cli.build_parser()
    args = parser.parse_args(["fetch", "stock", "--ticker", "X", "--start", "2020-01-01", "--end", "2020-02-01"])
    with patch("aq_cli.fetch_adhoc_asset", fetch_mock):
        assert args.func(args) == 1


def test_fetch_prints_added_config_status(capsys):
    fetch_mock = MagicMock(return_value=_sample_fetch_report(action="written", config_status="added"))
    parser = aq_cli.build_parser()
    args = parser.parse_args(
        ["fetch", "crypto", "--ticker", "DOGEUSD", "--start", "2023-01-01", "--end", "2023-01-03", "--apply"]
    )
    with patch("aq_cli.fetch_adhoc_asset", fetch_mock):
        args.func(args)

    out = capsys.readouterr().out
    assert "added a new DOGEUSD asset block" in out
    assert "Ready to prepare training" in out


def test_fetch_prints_already_exists_config_status(capsys):
    fetch_mock = MagicMock(return_value=_sample_fetch_report(action="written", config_status="already_exists"))
    parser = aq_cli.build_parser()
    args = parser.parse_args(
        ["fetch", "crypto", "--ticker", "DOGEUSD", "--start", "2023-01-01", "--end", "2023-01-03", "--apply"]
    )
    with patch("aq_cli.fetch_adhoc_asset", fetch_mock):
        args.func(args)

    assert "already configured" in capsys.readouterr().out


# --- fetch futures/options (IB-backed) ---------------------------------------


def test_fetch_futures_accepts_new_asset_class():
    parser = aq_cli.build_parser()
    args = parser.parse_args(["fetch", "futures", "--ticker", "ES", "--start", "2020-01-01", "--end", "2020-02-01", "--expiry", "2020-06-19"])
    assert args.asset_class == "futures"


def test_fetch_options_accepts_strike_and_right():
    parser = aq_cli.build_parser()
    args = parser.parse_args(
        ["fetch", "options", "--ticker", "SPY", "--start", "2020-01-01", "--end", "2020-02-01",
         "--expiry", "2020-06-19", "--strike", "300", "--right", "call"]
    )
    assert args.strike == 300.0
    assert args.right == "call"


def test_fetch_futures_requires_expiry():
    parser = aq_cli.build_parser()
    args = parser.parse_args(["fetch", "futures", "--ticker", "ES", "--start", "2020-01-01", "--end", "2020-02-01"])
    exit_code = args.func(args)
    assert exit_code == 1


def test_fetch_options_requires_strike_and_right():
    parser = aq_cli.build_parser()
    args = parser.parse_args(
        ["fetch", "options", "--ticker", "SPY", "--start", "2020-01-01", "--end", "2020-02-01", "--expiry", "2020-06-19"]
    )
    exit_code = args.func(args)
    assert exit_code == 1


def test_fetch_futures_fails_cleanly_when_ib_not_configured(capsys):
    parser = aq_cli.build_parser()
    args = parser.parse_args(
        ["fetch", "futures", "--ticker", "ES", "--start", "2020-01-01", "--end", "2020-02-01", "--expiry", "2020-06-19"]
    )
    with patch("aq_cli.connect_ib", side_effect=aq_cli.IBNotConfiguredError("IB is not configured: ...")):
        exit_code = args.func(args)

    assert exit_code == 1
    assert "IB is not configured" in capsys.readouterr().err


def test_fetch_futures_connects_and_disconnects_ib_around_fetch():
    fake_ib = MagicMock()
    fetch_mock = MagicMock(return_value=_sample_fetch_report(asset_class="futures", ticker="ES"))
    parser = aq_cli.build_parser()
    args = parser.parse_args(
        ["fetch", "futures", "--ticker", "ES", "--start", "2020-01-01", "--end", "2020-02-01", "--expiry", "2020-06-19"]
    )
    with patch("aq_cli.connect_ib", return_value=fake_ib), patch("aq_cli.disconnect_ib") as disconnect_mock, patch(
        "aq_cli.fetch_adhoc_asset", fetch_mock
    ):
        args.func(args)

    disconnect_mock.assert_called_once_with(fake_ib)
    fetch_mock.assert_called_once()
    assert fetch_mock.call_args.kwargs["fetch_fn"] is not None


def test_fetch_futures_disconnects_ib_even_if_fetch_raises():
    fake_ib = MagicMock()
    parser = aq_cli.build_parser()
    args = parser.parse_args(
        ["fetch", "futures", "--ticker", "ES", "--start", "2020-01-01", "--end", "2020-02-01", "--expiry", "2020-06-19"]
    )
    with patch("aq_cli.connect_ib", return_value=fake_ib), patch("aq_cli.disconnect_ib") as disconnect_mock, patch(
        "aq_cli.fetch_adhoc_asset", side_effect=RuntimeError("boom")
    ):
        try:
            args.func(args)
            assert False, "expected RuntimeError to propagate"
        except RuntimeError:
            pass

    disconnect_mock.assert_called_once_with(fake_ib)


# --- ib status ----------------------------------------------------------------


def test_ib_status_disabled(capsys):
    parser = aq_cli.build_parser()
    args = parser.parse_args(["ib", "status"])
    with patch("aq_cli.ib_readiness_status", return_value="disabled"):
        exit_code = args.func(args)

    assert exit_code == 0
    assert "disabled" in capsys.readouterr().out


def test_ib_status_credentials_missing(capsys):
    parser = aq_cli.build_parser()
    args = parser.parse_args(["ib", "status"])
    with patch("aq_cli.ib_readiness_status", return_value="enabled_but_lean_credentials_missing"):
        exit_code = args.func(args)

    out = capsys.readouterr().out
    assert exit_code == 1
    assert "aq lean set ib-account" in out


def test_ib_status_reachable(capsys):
    parser = aq_cli.build_parser()
    args = parser.parse_args(["ib", "status"])
    with patch("aq_cli.ib_readiness_status", return_value="ready"), patch(
        "aq_cli.attempt_connection", return_value=(True, "reachable")
    ):
        exit_code = args.func(args)

    assert exit_code == 0
    assert "reachable" in capsys.readouterr().out


def test_ib_status_not_reachable(capsys):
    parser = aq_cli.build_parser()
    args = parser.parse_args(["ib", "status"])
    with patch("aq_cli.ib_readiness_status", return_value="ready"), patch(
        "aq_cli.attempt_connection", return_value=(False, "connection failed — timeout")
    ):
        exit_code = args.func(args)

    out = capsys.readouterr().out
    assert exit_code == 1
    assert "not reachable" in out


# --- assets status ------------------------------------------------------------


def test_assets_status_reports_all_sections(capsys):
    parser = aq_cli.build_parser()
    args = parser.parse_args(["assets", "status"])
    with patch("monitoring.assets_status.ib_readiness_status", return_value="disabled"), patch(
        "monitoring.assets_status.load_futures_contract_specs", return_value={"ES": {}, "NQ": {}}
    ), patch(
        "monitoring.assets_status.load_cached_fred_series",
        return_value={"treasury_10yr": [{"date": date(2026, 7, 1), "value": 0.04}]},
    ):
        exit_code = args.func(args)

    out = capsys.readouterr().out
    assert exit_code == 0
    assert "IB: disabled" in out
    assert "futures_risk.enabled: False" in out
    assert "options_risk.enabled: False" in out
    assert "Futures contract specs loaded: 2" in out
    assert "FRED cache: 1 series populated" in out
    assert "2026-07-01" in out
    assert "Configured futures assets: 0" in out
    assert "Configured options assets: 0" in out


def test_assets_status_empty_fred_cache_reports_never_populated(capsys):
    parser = aq_cli.build_parser()
    args = parser.parse_args(["assets", "status"])
    with patch("monitoring.assets_status.ib_readiness_status", return_value="disabled"), patch(
        "monitoring.assets_status.load_futures_contract_specs", return_value={}
    ), patch("monitoring.assets_status.load_cached_fred_series", return_value={}):
        args.func(args)

    assert "never populated" in capsys.readouterr().out


def test_assets_status_counts_configured_futures_and_options_assets(tmp_path, capsys, monkeypatch):
    config = {
        "phase_v2": {"futures_risk": {"enabled": True}, "options_risk": {"enabled": False}},
        "phase1": {
            "universe": {
                "assets": [
                    {"ticker": "ES", "asset_class": "future"},
                    {"ticker": "SPY_500C", "asset_class": "option"},
                    {"ticker": "SPY_490P", "asset_class": "option"},
                    {"ticker": "AAPL", "security_type": "equity"},
                ]
            }
        },
    }
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    lean_path = tmp_path / "lean.json"
    lean_path.write_text(json.dumps({"ib-account": "", "ib-user-name": ""}), encoding="utf-8")
    monkeypatch.setattr(aq_cli, "CONFIG_PATH", config_path)
    monkeypatch.setattr(aq_cli, "LEAN_JSON_PATH", lean_path)

    parser = aq_cli.build_parser()
    args = parser.parse_args(["assets", "status"])
    with patch("monitoring.assets_status.load_futures_contract_specs", return_value={}), patch(
        "monitoring.assets_status.load_cached_fred_series", return_value={}
    ):
        args.func(args)

    out = capsys.readouterr().out
    assert "futures_risk.enabled: True" in out
    assert "options_risk.enabled: False" in out
    assert "Configured futures assets: 1" in out
    assert "Configured options assets: 2" in out


# --- update-check ---------------------------------------------------------


def test_parse_simple_version_accepts_clean_dotted_integers():
    assert aq_cli._parse_simple_version("1.2.3") == (1, 2, 3)
    assert aq_cli._parse_simple_version("0.1.0") == (0, 1, 0)


def test_parse_simple_version_rejects_dev_and_local_builds():
    # setuptools-scm's fallback for untagged installs - must never be
    # compared as if it were a real release, or every dev build would look
    # "outdated" forever.
    assert aq_cli._parse_simple_version("0.1.dev35+gc744f9ca4.d20260704") is None
    assert aq_cli._parse_simple_version("") is None


def test_update_cache_round_trips(tmp_path):
    cache_path = tmp_path / "update_check.json"
    with patch("aq_cli.UPDATE_CACHE_PATH", cache_path):
        aq_cli._write_update_cache("9.9.9")
        cache = aq_cli._read_update_cache()

    assert cache["latest_version"] == "9.9.9"
    assert "last_checked" in cache


def test_read_update_cache_returns_empty_dict_when_missing(tmp_path):
    with patch("aq_cli.UPDATE_CACHE_PATH", tmp_path / "does_not_exist.json"):
        assert aq_cli._read_update_cache() == {}


def test_check_for_update_prints_notice_when_outdated(tmp_path, capsys):
    with patch("aq_cli.UPDATE_CACHE_PATH", tmp_path / "update_check.json"), patch(
        "aq_cli.installed_version", return_value="1.0.0"
    ), patch("aq_cli._fetch_latest_version_from_pypi", return_value="2.0.0"):
        aq_cli.check_for_update()

    err = capsys.readouterr().err
    assert "2.0.0" in err
    assert "1.0.0" in err
    assert "pip install --upgrade aether-quant" in err


def test_check_for_update_silent_when_up_to_date(tmp_path, capsys):
    with patch("aq_cli.UPDATE_CACHE_PATH", tmp_path / "update_check.json"), patch(
        "aq_cli.installed_version", return_value="2.0.0"
    ), patch("aq_cli._fetch_latest_version_from_pypi", return_value="2.0.0"):
        aq_cli.check_for_update()

    assert capsys.readouterr().err == ""


def test_check_for_update_silent_on_dev_build(tmp_path, capsys):
    with patch("aq_cli.UPDATE_CACHE_PATH", tmp_path / "update_check.json"), patch(
        "aq_cli.installed_version", return_value="0.1.dev35+gc744f9ca4.d20260704"
    ), patch("aq_cli._fetch_latest_version_from_pypi", return_value="2.0.0"):
        aq_cli.check_for_update()

    assert capsys.readouterr().err == ""


def test_check_for_update_never_raises_when_pypi_unreachable(tmp_path, capsys):
    with patch("aq_cli.UPDATE_CACHE_PATH", tmp_path / "update_check.json"), patch(
        "aq_cli.installed_version", return_value="1.0.0"
    ), patch("aq_cli._fetch_latest_version_from_pypi", side_effect=Exception("network down")):
        aq_cli.check_for_update()  # must not raise

    assert capsys.readouterr().err == ""


def test_check_for_update_respects_skip_env_var(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("AQ_SKIP_UPDATE_CHECK", "1")
    fetch_mock = MagicMock(return_value="2.0.0")
    with patch("aq_cli.UPDATE_CACHE_PATH", tmp_path / "update_check.json"), patch(
        "aq_cli.installed_version", return_value="1.0.0"
    ), patch("aq_cli._fetch_latest_version_from_pypi", fetch_mock):
        aq_cli.check_for_update()

    fetch_mock.assert_not_called()
    assert capsys.readouterr().err == ""


def test_check_for_update_uses_cache_within_interval(tmp_path):
    cache_path = tmp_path / "update_check.json"
    with patch("aq_cli.UPDATE_CACHE_PATH", cache_path):
        aq_cli._write_update_cache("1.5.0")
        fetch_mock = MagicMock(return_value="9.9.9")
        with patch("aq_cli._fetch_latest_version_from_pypi", fetch_mock):
            latest = aq_cli._latest_known_version()

    fetch_mock.assert_not_called()
    assert latest == "1.5.0"


# --- test badge -------------------------------------------------------------


def _write_readme_with_test_badge_markers(path) -> None:
    path.write_text(
        f"# Aether Quant\n\n{aq_cli._TEST_BADGE_MARKER_START}old badge{aq_cli._TEST_BADGE_MARKER_END}\n\nMore.\n",
        encoding="utf-8",
    )


def test_update_readme_test_badge_rewrites_between_markers(tmp_path):
    readme_path = tmp_path / "README.md"
    _write_readme_with_test_badge_markers(readme_path)

    with patch("aq_cli.README_PATH", readme_path):
        aq_cli._update_readme_test_badge(passed=507, failed=0)

    text = readme_path.read_text(encoding="utf-8")
    assert "old badge" not in text
    assert "507%2F507" in text
    assert "brightgreen" in text


def test_update_readme_test_badge_turns_red_on_failure(tmp_path):
    readme_path = tmp_path / "README.md"
    _write_readme_with_test_badge_markers(readme_path)

    with patch("aq_cli.README_PATH", readme_path):
        aq_cli._update_readme_test_badge(passed=500, failed=7)

    text = readme_path.read_text(encoding="utf-8")
    assert "500%2F507" in text
    assert "-red?" in text


def test_update_readme_test_badge_noop_when_markers_missing(tmp_path):
    readme_path = tmp_path / "README.md"
    readme_path.write_text("# Aether Quant\n\nNo markers.\n", encoding="utf-8")

    with patch("aq_cli.README_PATH", readme_path):
        aq_cli._update_readme_test_badge(passed=5, failed=0)

    assert readme_path.read_text(encoding="utf-8") == "# Aether Quant\n\nNo markers.\n"


def test_update_readme_test_badge_noop_when_nothing_collected(tmp_path):
    readme_path = tmp_path / "README.md"
    _write_readme_with_test_badge_markers(readme_path)

    with patch("aq_cli.README_PATH", readme_path):
        aq_cli._update_readme_test_badge(passed=0, failed=0)

    assert "old badge" in readme_path.read_text(encoding="utf-8")


def test_cmd_test_parses_captured_output_and_updates_badge():
    badge_mock = MagicMock()
    with patch("aq_cli._run_captured", return_value=(0, "505 passed, 2 failed in 12.3s")), patch(
        "aq_cli._update_readme_test_badge", badge_mock
    ):
        parser = aq_cli.build_parser()
        args = parser.parse_args(["test"])
        exit_code = args.func(args)

    badge_mock.assert_called_once_with(505, 2)
    assert exit_code == 0


def test_cmd_test_treats_errors_as_failures_for_the_badge():
    badge_mock = MagicMock()
    with patch("aq_cli._run_captured", return_value=(2, "3 passed, 1 error in 1.0s")), patch(
        "aq_cli._update_readme_test_badge", badge_mock
    ):
        parser = aq_cli.build_parser()
        args = parser.parse_args(["test"])
        args.func(args)

    badge_mock.assert_called_once_with(3, 1)


# ---------------------------------------------------------------------------
# aq config
# ---------------------------------------------------------------------------


def _config_fixture(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "phase_v2": {
                    "gating_network": {"baseline_weight": 0.25, "learned_model_enabled": True},
                    "retraining": {"eligible_severities": ["warning", "critical"]},
                }
            },
            indent=4,
        )
        + "\n",
        encoding="utf-8",
    )
    return config_path


def _run_config(config_path, argv, capsys):
    parser = aq_cli.build_parser()
    args = parser.parse_args(["config", *argv])
    with patch("aq_cli.CONFIG_PATH", config_path):
        exit_code = args.func(args)
    return exit_code, capsys.readouterr()


def test_config_bare_dumps_entire_file(tmp_path, capsys):
    config_path = _config_fixture(tmp_path)

    exit_code, captured = _run_config(config_path, [], capsys)

    assert exit_code == 0
    assert json.loads(captured.out) == json.loads(config_path.read_text(encoding="utf-8"))


def test_config_get_existing_nested_scalar(tmp_path, capsys):
    config_path = _config_fixture(tmp_path)

    exit_code, captured = _run_config(config_path, ["get", "phase_v2.gating_network.baseline_weight"], capsys)

    assert exit_code == 0
    assert captured.out.strip() == "0.25"


def test_config_get_nested_dict_returns_json(tmp_path, capsys):
    config_path = _config_fixture(tmp_path)

    exit_code, captured = _run_config(config_path, ["get", "phase_v2.gating_network"], capsys)

    assert exit_code == 0
    assert json.loads(captured.out) == {"baseline_weight": 0.25, "learned_model_enabled": True}


def test_config_get_missing_key_errors(tmp_path, capsys):
    config_path = _config_fixture(tmp_path)

    exit_code, captured = _run_config(config_path, ["get", "phase_v2.does_not_exist"], capsys)

    assert exit_code == 1
    assert "no such config key" in captured.err


def test_config_set_flips_bool_and_round_trips(tmp_path, capsys):
    config_path = _config_fixture(tmp_path)

    exit_code, captured = _run_config(
        config_path, ["set", "phase_v2.gating_network.learned_model_enabled", "false"], capsys
    )
    assert exit_code == 0
    assert "True -> False" in captured.out

    _, captured = _run_config(config_path, ["get", "phase_v2.gating_network.learned_model_enabled"], capsys)
    assert captured.out.strip() == "false"


def test_config_set_list_with_json_array(tmp_path, capsys):
    config_path = _config_fixture(tmp_path)

    exit_code, _ = _run_config(
        config_path, ["set", "phase_v2.retraining.eligible_severities", '["critical"]'], capsys
    )

    assert exit_code == 0
    updated = json.loads(config_path.read_text(encoding="utf-8"))
    assert updated["phase_v2"]["retraining"]["eligible_severities"] == ["critical"]


def test_config_set_non_json_bare_word_falls_back_to_string(tmp_path, capsys):
    config_path = _config_fixture(tmp_path)

    exit_code, _ = _run_config(config_path, ["set", "phase_v2.gating_network.baseline_weight", "learned"], capsys)

    assert exit_code == 0
    updated = json.loads(config_path.read_text(encoding="utf-8"))
    assert updated["phase_v2"]["gating_network"]["baseline_weight"] == "learned"


def test_config_set_missing_key_errors_and_leaves_file_untouched(tmp_path, capsys):
    config_path = _config_fixture(tmp_path)
    original = config_path.read_text(encoding="utf-8")

    exit_code, captured = _run_config(config_path, ["set", "phase_v2.does_not_exist", "1"], capsys)

    assert exit_code == 1
    assert "no such config key" in captured.err
    assert config_path.read_text(encoding="utf-8") == original


def test_config_set_writes_backup_matching_pre_set_content(tmp_path, capsys):
    config_path = _config_fixture(tmp_path)
    original = config_path.read_text(encoding="utf-8")

    _run_config(config_path, ["set", "phase_v2.gating_network.baseline_weight", "0.5"], capsys)

    backup_path = config_path.with_suffix(".json.bak")
    assert backup_path.exists()
    assert backup_path.read_text(encoding="utf-8") == original


def test_config_set_type_change_prints_warning_but_still_writes(tmp_path, capsys):
    config_path = _config_fixture(tmp_path)

    exit_code, captured = _run_config(config_path, ["set", "phase_v2.gating_network.baseline_weight", "hello"], capsys)

    assert exit_code == 0
    assert "WARNING: type changed from float to str" in captured.err
    updated = json.loads(config_path.read_text(encoding="utf-8"))
    assert updated["phase_v2"]["gating_network"]["baseline_weight"] == "hello"


def test_config_keys_lists_every_leaf(tmp_path, capsys):
    config_path = _config_fixture(tmp_path)

    exit_code, captured = _run_config(config_path, ["keys"], capsys)

    assert exit_code == 0
    keys = captured.out.strip().splitlines()
    assert "phase_v2.gating_network.baseline_weight" in keys
    assert "phase_v2.gating_network.learned_model_enabled" in keys
    assert "phase_v2.retraining.eligible_severities" in keys


def test_config_keys_scoped_to_prefix(tmp_path, capsys):
    config_path = _config_fixture(tmp_path)

    exit_code, captured = _run_config(config_path, ["keys", "phase_v2.gating_network"], capsys)

    assert exit_code == 0
    keys = captured.out.strip().splitlines()
    assert set(keys) == {"phase_v2.gating_network.baseline_weight", "phase_v2.gating_network.learned_model_enabled"}


# ---------------------------------------------------------------------------
# aq lean — same _dispatch_json_config_command as aq config, just pointed at
# lean.json; the shared dispatch logic's edge cases (missing key, type
# warning, JSON coercion, ...) are already covered above, so this block only
# confirms the wiring (LEAN_JSON_PATH used, lean_command attr used).
# ---------------------------------------------------------------------------


def _lean_fixture(tmp_path):
    lean_path = tmp_path / "lean.json"
    lean_path.write_text(
        json.dumps({"ib-trading-mode": "paper", "symbol-minute-limit": 10000}, indent=4) + "\n",
        encoding="utf-8",
    )
    return lean_path


def _run_lean(lean_path, argv, capsys):
    parser = aq_cli.build_parser()
    args = parser.parse_args(["lean", *argv])
    with patch("aq_cli.LEAN_JSON_PATH", lean_path):
        exit_code = args.func(args)
    return exit_code, capsys.readouterr()


def test_lean_bare_dumps_entire_file(tmp_path, capsys):
    lean_path = _lean_fixture(tmp_path)

    exit_code, captured = _run_lean(lean_path, [], capsys)

    assert exit_code == 0
    assert json.loads(captured.out) == json.loads(lean_path.read_text(encoding="utf-8"))


def test_lean_get_existing_key(tmp_path, capsys):
    lean_path = _lean_fixture(tmp_path)

    exit_code, captured = _run_lean(lean_path, ["get", "ib-trading-mode"], capsys)

    assert exit_code == 0
    assert captured.out.strip() == "paper"


def test_lean_set_writes_value_and_backup(tmp_path, capsys):
    lean_path = _lean_fixture(tmp_path)
    original = lean_path.read_text(encoding="utf-8")

    exit_code, captured = _run_lean(lean_path, ["set", "ib-trading-mode", "live"], capsys)

    assert exit_code == 0
    assert "paper -> 'live'" in captured.out or "'paper' -> 'live'" in captured.out
    assert json.loads(lean_path.read_text(encoding="utf-8"))["ib-trading-mode"] == "live"
    backup_path = lean_path.with_suffix(".json.bak")
    assert backup_path.exists()
    assert backup_path.read_text(encoding="utf-8") == original


def test_lean_keys_lists_leaves(tmp_path, capsys):
    lean_path = _lean_fixture(tmp_path)

    exit_code, captured = _run_lean(lean_path, ["keys"], capsys)

    assert exit_code == 0
    keys = captured.out.strip().splitlines()
    assert set(keys) == {"ib-trading-mode", "symbol-minute-limit"}


def test_lean_get_missing_key_errors(tmp_path, capsys):
    lean_path = _lean_fixture(tmp_path)

    exit_code, captured = _run_lean(lean_path, ["get", "does-not-exist"], capsys)

    assert exit_code == 1
    assert "no such config key" in captured.err
