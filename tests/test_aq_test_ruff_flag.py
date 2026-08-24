"""V5.3.10 - tests for `aq test --ruff` flag behavior."""

from __future__ import annotations

import aq_cli


def test_ruff_flag_defaults_to_false():
    parser = aq_cli.build_parser()
    args = parser.parse_args(["test"])
    assert args.ruff is False


def test_ruff_flag_parses():
    parser = aq_cli.build_parser()
    args = parser.parse_args(["test", "--ruff"])
    assert args.ruff is True


def test_ruff_flag_clean_repo_passes_through(monkeypatch, capsys):
    """On the real (clean) repo, --ruff runs ruff then continues into pytest.
    We monkeypatch pytest invocation to avoid running 2700 tests here."""
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        class R:
            returncode = 0
        return R()

    monkeypatch.setattr("subprocess.run", fake_run)

    parser = aq_cli.build_parser()
    args = parser.parse_args(["test", "--ruff"])

    captured_cmd = []
    monkeypatch.setattr(aq_cli, "_run_captured", lambda cmd, cwd=None: (captured_cmd.append(cmd), (0, "2751 passed"))[1])

    exit_code = aq_cli.cmd_test(args)
    assert exit_code == 0
    assert any("ruff" in str(c) for c in calls), "ruff must run before pytest"


def test_ruff_flag_fails_fast_on_lint_error(monkeypatch):
    import subprocess as sp

    def failing_run(cmd, **kwargs):
        if "ruff" in str(cmd):
            class R:
                returncode = 1
            return R()
        raise AssertionError("pytest must NOT run when ruff fails")

    monkeypatch.setattr(sp, "run", failing_run)

    parser = aq_cli.build_parser()
    args = parser.parse_args(["test", "--ruff"])
    exit_code = aq_cli.cmd_test(args)
    assert exit_code == 1
