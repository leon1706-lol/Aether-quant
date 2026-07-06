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

    fetch_mock.assert_called_once_with("crypto", "DOGEUSD", "2023-01-01", "2023-01-03", apply=False)
    assert exit_code == 0


def test_fetch_apply_flag_is_forwarded():
    fetch_mock = MagicMock(return_value=_sample_fetch_report(action="written", config_status="added"))
    parser = aq_cli.build_parser()
    args = parser.parse_args(
        ["fetch", "crypto", "--ticker", "DOGEUSD", "--start", "2023-01-01", "--end", "2023-01-03", "--apply"]
    )
    with patch("aq_cli.fetch_adhoc_asset", fetch_mock):
        args.func(args)

    fetch_mock.assert_called_once_with("crypto", "DOGEUSD", "2023-01-01", "2023-01-03", apply=True)


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
