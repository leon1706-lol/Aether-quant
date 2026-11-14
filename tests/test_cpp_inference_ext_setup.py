"""cpp_inference_ext/setup.py declares the optional accelerator's one extension (V6.6.6, #359). No compiler is needed:
pybind11's helpers and setuptools' `setup` are stand-ins that record what the script asks for."""

from __future__ import annotations

import runpy
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_the_build_script_declares_the_linear_batched_extension(monkeypatch):
    helpers = types.ModuleType("pybind11.setup_helpers")
    helpers.Pybind11Extension = lambda name, sources, **options: {"name": name, "sources": sources, **options}
    helpers.build_ext = object
    monkeypatch.setitem(sys.modules, "pybind11", types.ModuleType("pybind11"))
    monkeypatch.setitem(sys.modules, "pybind11.setup_helpers", helpers)
    recorded = {}
    import setuptools

    monkeypatch.setattr(setuptools, "setup", lambda **kwargs: recorded.update(kwargs))
    runpy.run_path(str(ROOT / "cpp_inference_ext" / "setup.py"), run_name="__main__")

    assert recorded["name"] == "cpp_inference" and recorded["cmdclass"] == {"build_ext": object}
    assert recorded["ext_modules"] == [{"name": "cpp_inference", "sources": ["src/linear_batched.cpp"], "cxx_std": 17}]
    assert (ROOT / "cpp_inference_ext" / "src" / "linear_batched.cpp").is_file()
