"""Does `except Exception` catch a Python error behind Lean's star import? (V6.5.0) One SMOKE_JSON line, then the run ends."""

from AlgorithmImports import *  # noqa: F403

import builtins
import json


class ExceptionScopeSmoke(QCAlgorithm):  # noqa: F405
    def initialize(self):
        self.set_start_date(2014, 6, 6)
        self.set_end_date(2014, 6, 6)
        self.set_cash(100000)
        report = {
            "kind": "exception_scope",
            "name_in_module": repr(Exception),
            "is_builtin": Exception is builtins.Exception,
            "mro": [repr(item) for item in getattr(Exception, "__mro__", [])],
        }
        try:
            try:
                None.Symbol
            except Exception:  # the star import's Exception, as main.py has it
                report["star_exception_catches_python_error"] = True
        except BaseException as error:
            report["star_exception_catches_python_error"] = False
            report["escaped_as"] = type(error).__name__
        try:
            try:
                self.add_equity("AAPL", "not a resolution")  # a .NET binding error
            except builtins.Exception as error:
                report["builtin_exception_catches_clr_error"] = True
                report["clr_error_type"] = type(error).__name__
        except BaseException as error:
            report["builtin_exception_catches_clr_error"] = False
            report["clr_escaped_as"] = type(error).__name__
        try:
            from System import ArgumentException

            try:
                raise ArgumentException("from .NET")
            except builtins.Exception as error:
                report["builtin_exception_catches_raised_clr"] = True
                report["raised_clr_type"] = type(error).__name__
        except BaseException as error:
            report["builtin_exception_catches_raised_clr"] = False
            report["raised_clr_escaped_as"] = type(error).__name__
        self.debug("SMOKE_JSON " + json.dumps(report, default=str))

    def on_data(self, slice):
        pass
