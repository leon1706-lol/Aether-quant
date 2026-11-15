"""fuzz/run_fuzz.py (V6.6.7, #363) against a stand-in Atheris: the CI entry point hands the named target to libFuzzer."""

from __future__ import annotations

import contextlib
import runpy
import sys
from pathlib import Path

import pytest
from script_loader import fake_module

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "fuzz" / "run_fuzz.py"


def _fake_atheris(monkeypatch) -> list:
    calls: list = []
    fake_module(
        monkeypatch, "atheris",
        instrument_imports=contextlib.nullcontext,
        Setup=lambda argv, target: calls.append(("Setup", list(argv), target)),
        Fuzz=lambda: calls.append(("Fuzz",)),
    )
    return calls


def test_scorecard_sees_the_atheris_import():
    assert "\nimport atheris\n" in RUNNER.read_text(encoding="utf-8")


def test_main_sets_up_the_named_target(monkeypatch):
    calls = _fake_atheris(monkeypatch)
    monkeypatch.setattr(sys, "argv", [str(RUNNER), "json_safety", "-runs=1", "fuzz/corpus/json_safety"])
    namespace = runpy.run_path(str(RUNNER), run_name="__main__")
    assert calls[0][0] == "Setup" and calls[0][1] == [str(RUNNER), "-runs=1", "fuzz/corpus/json_safety"]
    assert calls[0][2] is namespace["TARGETS"]["json_safety"]
    assert calls[1] == ("Fuzz",)


def test_an_unknown_target_is_a_usage_error(monkeypatch):
    _fake_atheris(monkeypatch)
    namespace = runpy.run_path(str(RUNNER), run_name="not_main")
    with pytest.raises(SystemExit, match="usage"):
        namespace["main"](["run_fuzz.py", "nope"])
    with pytest.raises(SystemExit, match="usage"):
        namespace["main"](["run_fuzz.py"])
