"""scripts/lean_smoke/exception_scope.py against a stand-in for Lean's star import (V6.6.6): both outcomes of each probe."""

from __future__ import annotations

import builtins
import json
import sys
import types

from script_loader import load_script


class _Escape(BaseException):
    pass


def _lean(monkeypatch, *, star_exception, binding_error, raised_base):
    stub = types.ModuleType("AlgorithmImports")
    stub.Exception = star_exception

    class QCAlgorithm:
        def __init__(self):
            self.lines = []

        def set_start_date(self, *args):
            pass

        set_end_date = set_cash = set_start_date

        def add_equity(self, ticker, resolution):
            raise binding_error

        def debug(self, message):
            self.lines.append(message)

    stub.QCAlgorithm = QCAlgorithm
    system = types.ModuleType("System")
    system.ArgumentException = type("ArgumentException", (raised_base,), {})
    monkeypatch.setitem(sys.modules, "AlgorithmImports", stub)
    monkeypatch.setitem(sys.modules, "System", system)
    module = load_script("lean_smoke/exception_scope")
    algorithm = module.ExceptionScopeSmoke()
    algorithm.initialize()
    algorithm.on_data(None)
    (line,) = algorithm.lines
    assert line.startswith("SMOKE_JSON ")
    return json.loads(line[len("SMOKE_JSON "):])


def test_when_every_error_is_caught(monkeypatch):
    report = _lean(monkeypatch, star_exception=builtins.Exception, binding_error=ValueError("bad"), raised_base=builtins.Exception)
    assert report["is_builtin"] is True and report["star_exception_catches_python_error"] is True
    assert report["builtin_exception_catches_clr_error"] is True and report["clr_error_type"] == "ValueError"
    assert report["builtin_exception_catches_raised_clr"] is True and report["raised_clr_type"] == "ArgumentException"


def test_when_every_error_escapes(monkeypatch):
    clr_exception = type("ClrException", (builtins.Exception,), {})
    report = _lean(monkeypatch, star_exception=clr_exception, binding_error=_Escape(), raised_base=BaseException)
    assert report["is_builtin"] is False
    assert report["star_exception_catches_python_error"] is False and report["escaped_as"] == "AttributeError"
    assert report["builtin_exception_catches_clr_error"] is False and report["clr_escaped_as"] == "_Escape"
    assert report["builtin_exception_catches_raised_clr"] is False and report["raised_clr_escaped_as"] == "ArgumentException"
