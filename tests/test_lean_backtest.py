"""Tests for retraining.lean_backtest — V2-17.

Conventions: no test classes, module-level helpers, shutil.which/subprocess.run
mocked via unittest.mock.patch.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

from retraining.lean_backtest import find_lean_binary, run_lean_backtest

_CONFIG = {"run_lean_backtest": True, "lean_binary": "lean", "lean_timeout_seconds": 60}


def test_find_lean_binary_returns_none_when_missing():
    with patch("retraining.lean_backtest.shutil.which", return_value=None):
        assert find_lean_binary(_CONFIG) is None


def test_find_lean_binary_returns_path_when_present():
    with patch("retraining.lean_backtest.shutil.which", return_value="/usr/bin/lean"):
        assert find_lean_binary(_CONFIG) == "/usr/bin/lean"


def test_run_lean_backtest_never_attempts_subprocess_when_binary_missing():
    with patch("retraining.lean_backtest.shutil.which", return_value=None), patch(
        "retraining.lean_backtest.subprocess.run"
    ) as run_mock:
        result = run_lean_backtest(Path("ml/versions/abc"), _CONFIG)

    run_mock.assert_not_called()
    assert result == {"ran": False, "ok": None, "output_path": None, "error": "lean_not_available"}


def test_run_lean_backtest_disabled_never_calls_which_or_subprocess():
    with patch("retraining.lean_backtest.shutil.which") as which_mock, patch(
        "retraining.lean_backtest.subprocess.run"
    ) as run_mock:
        result = run_lean_backtest(Path("ml/versions/abc"), {**_CONFIG, "run_lean_backtest": False})

    which_mock.assert_not_called()
    run_mock.assert_not_called()
    assert result["ran"] is False
    assert result["error"] == "lean_backtest_disabled"


def test_run_lean_backtest_returns_ok_true_on_success():
    completed = MagicMock(returncode=0)
    with patch("retraining.lean_backtest.shutil.which", return_value="/usr/bin/lean"), patch(
        "retraining.lean_backtest.subprocess.run", return_value=completed
    ):
        result = run_lean_backtest(Path("ml/versions/abc"), _CONFIG)

    assert result["ran"] is True
    assert result["ok"] is True


def test_run_lean_backtest_returns_ok_false_on_nonzero_exit():
    completed = MagicMock(returncode=1, stderr="failure", stdout="")
    with patch("retraining.lean_backtest.shutil.which", return_value="/usr/bin/lean"), patch(
        "retraining.lean_backtest.subprocess.run", return_value=completed
    ):
        result = run_lean_backtest(Path("ml/versions/abc"), _CONFIG)

    assert result["ran"] is True
    assert result["ok"] is False
    assert result["error"] == "failure"
