"""scripts/wheel_smoke.py's runtime (V6.6.6, #359): the import walk and its three outcomes, the subcommand list, the `--help` runs, the one-call library checks
and the installed-or-not decision of `main()`."""

from __future__ import annotations

import importlib
import subprocess
import sys
from types import SimpleNamespace

import pytest

import aq_cli
from script_loader import load_script


@pytest.fixture(scope="module")
def smoke():
    return load_script("wheel_smoke")


def test_the_module_walk_names_the_shipped_modules_and_every_package_member(smoke, monkeypatch):
    monkeypatch.setattr(smoke, "SHIPPED_PACKAGES", ("liquidity",))
    monkeypatch.setattr(smoke, "SHIPPED_MODULES", ("json_safety",))
    names = smoke._iter_module_names()
    assert names[0] == "json_safety" and "liquidity" in names and any(name.startswith("liquidity.") for name in names)


def test_imports_are_sorted_into_failures_tolerated_extras_and_crashes(smoke, monkeypatch):
    monkeypatch.setattr(smoke, "_iter_module_names", lambda: ["ok", "risk.gone", "tool.extra", "boom", "noname"])

    def fake_import(name):
        if name == "risk.gone":
            raise ModuleNotFoundError("missing", name="risk.gone")
        if name == "tool.extra":
            raise ModuleNotFoundError("missing", name="ib_insync")
        if name == "boom":
            raise ValueError("bad import")
        if name == "noname":
            raise ModuleNotFoundError("missing")

    monkeypatch.setattr(smoke.importlib, "import_module", fake_import)
    failures, tolerated = smoke.check_imports()
    assert any("missing first-party module 'risk.gone'" in line for line in failures) and any("import raised ValueError" in line for line in failures)
    assert len(tolerated) == 2 and any("ib_insync" in line for line in tolerated)


def test_the_subcommands_come_from_the_parser_choices(smoke, monkeypatch):
    assert "test" in smoke.subcommand_names()
    monkeypatch.setattr(aq_cli, "build_parser", lambda: SimpleNamespace(_actions=[SimpleNamespace(choices=None), SimpleNamespace(choices={})]))
    assert smoke.subcommand_names() == []


def test_a_help_run_that_exits_nonzero_is_named_with_its_error(smoke, monkeypatch):
    answers = {"good": subprocess.CompletedProcess([], 0, "", ""), "bad": subprocess.CompletedProcess([], 2, "", "usage: boom")}
    monkeypatch.setattr(smoke.subprocess, "run", lambda command, **kwargs: answers[command[2].split("'")[3]])
    assert smoke.check_help(["good"]) == [] and smoke.check_help(["good", "bad"])[0].startswith("aq bad --help exited 2: usage: boom")


def test_every_aether_quant_module_answers_its_smoke_call(smoke):
    assert smoke.check_library() == []


def test_a_library_module_that_will_not_import_or_answers_wrongly_is_reported(smoke, monkeypatch):
    real = importlib.import_module

    def fake_import(name):
        if name == "aether_quant.risk":
            raise ImportError("no risk")
        if name == "aether_quant.io":
            return SimpleNamespace(sanitize_json_finite=lambda value: ["wrong"])
        return real(name)

    monkeypatch.setattr(smoke.importlib, "import_module", fake_import)
    failures = smoke.check_library()
    assert any(line.startswith("aether_quant.risk: ImportError") for line in failures) and any("aether_quant.io: smoke call returned an unexpected value" in line for line in failures)


def test_a_checkout_import_is_refused_and_an_installed_wheel_is_judged(smoke, monkeypatch, capsys):
    assert smoke.main() == 1 and "not an installed wheel" in capsys.readouterr().out
    monkeypatch.setattr(aq_cli, "__file__", "/venv/lib/site-packages/aq_cli.py")
    monkeypatch.setattr(smoke, "check_imports", lambda: ([], ["tolerated line"]))
    monkeypatch.setattr(smoke, "check_library", lambda: [])
    monkeypatch.setattr(smoke, "subcommand_names", lambda: ["test"])
    monkeypatch.setattr(smoke, "check_help", lambda names: [])
    assert smoke.main() == 0 and "note: tolerated line" in capsys.readouterr().out
    monkeypatch.setattr(smoke, "check_library", lambda: ["library broke"])
    assert smoke.main() == 1 and "FAIL: library broke" in capsys.readouterr().out
    monkeypatch.setattr(smoke, "check_library", lambda: [])
    monkeypatch.setattr(smoke, "subcommand_names", lambda: [])
    assert smoke.main() == 1 and "no aq subcommands found" in capsys.readouterr().out and sys is not None


def test_the_script_run_as_main_refuses_a_checkout(monkeypatch, capsys):
    from script_loader import run_script

    assert run_script("wheel_smoke", [], monkeypatch) == 1 and "not an installed wheel" in capsys.readouterr().out
