"""Tests for aq_cli.py — the `aq` convenience CLI.

Conventions: no test classes, module-level helpers. Subprocess-wrapping
commands are tested by mocking aq_cli._run (the single choke point every
subprocess-based subcommand funnels through) and asserting the exact argv
built - never actually shelling out. trade-lock is tested via its own real
logic (risk.manual_override), same as tests/test_manual_override.py.
"""

import sys
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


def test_train_flags_are_mutually_exclusive():
    parser = aq_cli.build_parser()
    try:
        parser.parse_args(["train", "--dataset-only", "--init-only"])
        assert False, "expected SystemExit from argparse mutual exclusion"
    except SystemExit:
        pass


def test_test_wraps_pytest_tests_dir():
    run_mock = MagicMock(return_value=0)
    _parse_and_dispatch(["test"], run_mock)

    assert run_mock.call_args.args[0] == [sys.executable, "-m", "pytest", "tests/"]


def test_backtest_wraps_lean_backtest_dot():
    run_mock = MagicMock(return_value=0)
    with patch("aq_cli._find_quantconnect_lean_binary", return_value="lean"):
        _parse_and_dispatch(["backtest"], run_mock)

    assert run_mock.call_args.args[0] == ["lean", "backtest", "."]


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
