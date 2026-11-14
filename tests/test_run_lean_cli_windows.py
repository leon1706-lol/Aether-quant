"""scripts/run_lean_cli_windows.py (V6.6.6): Lean CLI's temp folders get Authenticated Users read access on Windows only, then
the CLI runs. The CLI and icacls are stand-ins, and the global `tempfile.mkdtemp` patch is undone after each test."""

from __future__ import annotations

import os
import sys
import tempfile
import types

import pytest

from script_loader import run_script


@pytest.fixture
def lean_cli(monkeypatch):
    calls = []
    lean = types.ModuleType("lean")
    lean_main = types.ModuleType("lean.main")
    lean_main.main = lambda: calls.append("lean main")
    monkeypatch.setitem(sys.modules, "lean", lean)
    monkeypatch.setitem(sys.modules, "lean.main", lean_main)
    monkeypatch.setattr(tempfile, "mkdtemp", tempfile.mkdtemp)  # restored after the test: the script replaces it
    return calls


@pytest.mark.parametrize("os_name", ["nt", "posix"])
def test_temp_folders_are_made_readable_on_windows_only_and_the_cli_runs(lean_cli, monkeypatch, tmp_path, os_name):
    import subprocess

    granted = []
    monkeypatch.setattr(subprocess, "run", lambda command, **kwargs: granted.append(command))
    assert run_script("run_lean_cli_windows", [], monkeypatch) is None
    assert lean_cli == ["lean main"]
    monkeypatch.setattr(os, "name", os_name)
    folder = tempfile.mkdtemp(dir=tmp_path)
    assert os.path.isdir(folder)
    assert bool(granted) is (os_name == "nt")
    if granted:
        assert granted[0][:2] == ["icacls", folder] and "*S-1-5-11:(OI)(CI)RX" in granted[0]
