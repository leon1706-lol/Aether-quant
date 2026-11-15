"""cpp_inference_ext/setup.py declares the optional accelerator's one extension (V6.6.6, #359), with opt-in sanitizer
and canary flags for CI's cpp-sanitizers job (V6.6.8, #380). No compiler is needed: pybind11's helpers and setuptools'
`setup` are stand-ins that record what the script asks for."""

from __future__ import annotations

import runpy
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _run_setup(monkeypatch, **env):
    for name in ("AQ_SANITIZE", "AQ_ASAN_CANARY"):
        monkeypatch.delenv(name, raising=False)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    helpers = types.ModuleType("pybind11.setup_helpers")
    helpers.Pybind11Extension = lambda name, sources, **options: {"name": name, "sources": sources, **options}
    helpers.build_ext = object
    monkeypatch.setitem(sys.modules, "pybind11", types.ModuleType("pybind11"))
    monkeypatch.setitem(sys.modules, "pybind11.setup_helpers", helpers)
    recorded = {}
    import setuptools

    monkeypatch.setattr(setuptools, "setup", lambda **kwargs: recorded.update(kwargs))
    runpy.run_path(str(ROOT / "cpp_inference_ext" / "setup.py"), run_name="__main__")
    return recorded


def test_the_build_script_declares_the_linear_batched_extension(monkeypatch):
    recorded = _run_setup(monkeypatch)

    assert recorded["name"] == "cpp_inference" and recorded["cmdclass"] == {"build_ext": object}
    assert recorded["ext_modules"] == [{"name": "cpp_inference", "sources": ["src/linear_batched.cpp"], "cxx_std": 17}]
    assert (ROOT / "cpp_inference_ext" / "src" / "linear_batched.cpp").is_file()


def test_sanitize_adds_the_asan_and_ubsan_flags_to_compile_and_link(monkeypatch):
    (extension,) = _run_setup(monkeypatch, AQ_SANITIZE=" address,undefined ")["ext_modules"]

    assert extension["extra_compile_args"][:2] == ["-fsanitize=address,undefined", "-fno-sanitize-recover=all"]
    assert "-fno-omit-frame-pointer" in extension["extra_compile_args"]
    assert extension["extra_link_args"] == ["-fsanitize=address,undefined"]
    assert "define_macros" not in extension


def test_the_canary_macro_is_defined_only_when_asked(monkeypatch):
    (asked,) = _run_setup(monkeypatch, AQ_ASAN_CANARY="1")["ext_modules"]
    (not_asked,) = _run_setup(monkeypatch, AQ_ASAN_CANARY="0")["ext_modules"]

    assert asked["define_macros"] == [("AQ_ASAN_CANARY", "1")]
    assert "define_macros" not in not_asked and "extra_compile_args" not in not_asked


def test_the_canary_is_compiled_only_under_its_macro():
    source = (ROOT / "cpp_inference_ext" / "src" / "linear_batched.cpp").read_text(encoding="utf-8")

    assert source.count("#ifdef AQ_ASAN_CANARY") == 2
    assert source.index("#ifdef AQ_ASAN_CANARY") < source.index("int asan_canary()")
