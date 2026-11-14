"""Every script under scripts/ with a command line answers `--help` when run as `__main__` (V6.6.6, #359).

A one-off research script is still run by hand, so its entry point has to work: this imports each one fresh, the way
`python scripts/<name>.py` would, and checks that argparse prints its usage and exits cleanly. The work each script does
is tested in its own tests/test_<name>.py."""

from __future__ import annotations

import pytest

from script_loader import SCRIPTS, run_script

# refuses to run inside the checkout before it parses anything (tests/test_wheel_smoke.py covers it)
_NOT_HERE = {"wheel_smoke"}
_CLI = sorted(
    name
    for path in SCRIPTS.rglob("*.py")
    if "__pycache__" not in path.parts and "argparse" in (text := path.read_text(encoding="utf-8")) and '__name__ == "__main__"' in text
    and (name := path.relative_to(SCRIPTS).with_suffix("").as_posix()) not in _NOT_HERE
)


def test_the_scripts_with_a_command_line_are_found():
    assert len(_CLI) > 50 and "cycle_daily" in _CLI


@pytest.mark.parametrize("script", _CLI)
def test_help_runs_as_a_script(script, monkeypatch, capsys):
    assert run_script(script, ["--help"], monkeypatch) == 0
    assert "usage:" in capsys.readouterr().out
