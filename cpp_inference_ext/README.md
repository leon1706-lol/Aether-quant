# cpp_inference_ext

An optional C++/pybind11 accelerator for `inference/exported_model.py::_linear_batched()`, the busiest primitive of the inference path (#32).

- **Never a hard dependency:** `inference/exported_model.py` tries `import cpp_inference` once and falls back to NumPy on any failure, with no error.
- **The odd name matters:** the folder must differ from the module it builds. A source folder called `cpp_inference` would shadow the installed module as an empty namespace package, because the repo root is on `sys.path`.
- **Contents:** `src/linear_batched.cpp` (`output[n, o] = sum_i weights[n, o, i] * input[n, i] + bias[n, o]`) and `setup.py`.

## Build

Needs a C++ compiler; on Windows, `cl.exe` from the Microsoft C++ Build Tools. `pybind11` is in `requirements/requirements-dev.txt`.

```powershell
pip install -e cpp_inference_ext/
python -c "import cpp_inference; print(cpp_inference.linear_batched)"
```

On this project's small matrices, any gain is in per-call dispatch overhead (#32).

## Sanitizers

This is the project's only memory-unsafe code, so CI's `cpp-sanitizers` job (#380) builds it with AddressSanitizer and UBSan on every push:

1. `AQ_SANITIZE=address,undefined AQ_ASAN_CANARY=1` builds a canary with `asan_canary()`, a deliberate heap overflow. The job requires it to abort with `heap-buffer-overflow`, which proves the instrumentation is live.
2. `AQ_SANITIZE=address,undefined` builds the real kernel. `tests/test_cpp_inference_kernel.py` (hypothesis: random shapes including zero sizes, dtypes, strided and Fortran layouts, NaN and inf) and `tests/test_exported_model.py` then run under it with `AQ_REQUIRE_CPP_INFERENCE=1`, so a missing build fails instead of skipping.

Both flags are read by `setup.py` and need GCC or Clang. The default build is unchanged. Python is a C program, so the job runs it with `LD_PRELOAD` set to `libasan` and, for the tests, `libstdc++` too (without it ASan's `__cxa_throw` interceptor aborts on the kernel's first C++ exception). To replay the job on a machine with Docker, run its steps inside `python:3.11-bookworm` with the repository mounted read-only and `--security-opt seccomp=unconfined` (Docker's default profile blocks a syscall the gcc-12 ASan runtime needs at startup).
