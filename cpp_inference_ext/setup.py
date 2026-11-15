"""Build script for the optional cpp_inference accelerator - never a hard
dependency (see development/Problems.md #32 and inference/exported_model.py's
_linear_batched() for the fallback contract). Install with:

    pip install -e cpp_inference_ext/

Requires a C++ compiler (MSVC on Windows, via the "Desktop development
with C++" / Build Tools workload - `cl.exe` must resolve, e.g. by running
this from a "Developer Command Prompt" or after vcvarsall.bat) and
pybind11 (`requirements/lock/build-ext.txt`).

`AQ_SANITIZE=address,undefined` builds with AddressSanitizer and UBSan (GCC/Clang; CI job `cpp-sanitizers`, #380), and
`AQ_ASAN_CANARY=1` adds `asan_canary()`, a deliberate heap overflow that proves the sanitizer is live.
"""

import os

from pybind11.setup_helpers import Pybind11Extension, build_ext
from setuptools import setup


def extension_options(environ=os.environ) -> dict:
    options: dict = {"cxx_std": 17}
    sanitizers = environ.get("AQ_SANITIZE", "").strip()
    if sanitizers:
        flag = f"-fsanitize={sanitizers}"
        options["extra_compile_args"] = [flag, "-fno-sanitize-recover=all", "-fno-omit-frame-pointer", "-g", "-O1"]
        options["extra_link_args"] = [flag]
    if environ.get("AQ_ASAN_CANARY") == "1":
        options["define_macros"] = [("AQ_ASAN_CANARY", "1")]
    return options


ext_modules = [
    Pybind11Extension(
        "cpp_inference",
        ["src/linear_batched.cpp"],
        **extension_options(),
    ),
]

setup(
    name="cpp_inference",
    version="0.1.0",
    description="Optional C++/pybind11 accelerator for inference/exported_model.py's batched linear layer",
    ext_modules=ext_modules,
    cmdclass={"build_ext": build_ext},
)
