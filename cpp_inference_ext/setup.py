"""Build script for the optional cpp_inference accelerator - never a hard
dependency (see development/Problems.md #32 and inference/exported_model.py's
_linear_batched() for the fallback contract). Install with:

    pip install -e cpp_inference/

Requires a C++ compiler (MSVC on Windows, via the "Desktop development
with C++" / Build Tools workload - `cl.exe` must resolve, e.g. by running
this from a "Developer Command Prompt" or after vcvarsall.bat) and
pybind11 (already a dev dependency of the sibling aether-vault project on
this machine; add it to requirements-dev.txt if building fresh elsewhere).
"""

from pybind11.setup_helpers import Pybind11Extension, build_ext
from setuptools import setup

ext_modules = [
    Pybind11Extension(
        "cpp_inference",
        ["src/linear_batched.cpp"],
        cxx_std=17,
    ),
]

setup(
    name="cpp_inference",
    version="0.1.0",
    description="Optional C++/pybind11 accelerator for inference/exported_model.py's batched linear layer",
    ext_modules=ext_modules,
    cmdclass={"build_ext": build_ext},
)
