# cpp_inference_ext

Optional C++/pybind11 accelerator for `inference/exported_model.py`'s
batched linear layer (`_linear_batched()`) — the most call-heavy primitive
in `main.py`'s per-bar inference hot path after the weight-array/stack
caching pass (see `development/Problems.md` #32). **Never a hard
dependency** — `inference/exported_model.py` attempts `import
cpp_inference` once at module load and falls back to the existing NumPy
`einsum`-based implementation on any import or call failure, same
deferred-optional-dependency convention as `ib_insync`
(`data_pipeline/ib_backfill.py`). `requirements.txt` is untouched by this
package; nothing else in this repo requires it to be built.

**Why the folder is named `cpp_inference_ext/` but builds a module named
`cpp_inference`:** a top-level source directory sharing the exact name of
the module it builds would shadow the properly-installed package as an
empty Python namespace package whenever the repo root is on `sys.path`
(which it always is here, via `pyproject.toml`'s `pythonpath = ["."]` for
pytest, and via `sys.path[0] == ''` for any script run from this
directory) — confirmed the hard way during this pass: `import
cpp_inference` resolved to the empty source folder instead of the
compiled extension until this folder was renamed. Keep this in mind if
ever renaming things back — the module name (`cpp_inference`, set in
`setup.py`'s `Pybind11Extension("cpp_inference", ...)` and
`src/linear_batched.cpp`'s `PYBIND11_MODULE(cpp_inference, m)`) must stay
different from this folder's own name.

- `src/linear_batched.cpp` — one function, `linear_batched(weights,
  input, bias)`, computing `output[n, o] = sum_i weights[n, o, i] *
  input[n, i] + bias[n, o]` — the exact same math as
  `inference/exported_model.py::_linear_batched()`'s
  `np.einsum("noi,ni->no", weights_stack, current) + bias_stack`, just
  compiled instead of interpreted through NumPy's einsum dispatch.
- `setup.py` — a standard `pybind11.setup_helpers.Pybind11Extension`
  build script.

## Building

Requires a C++ compiler. On Windows, the Microsoft C++ Build Tools
("Desktop development with C++" workload, or the standalone Build Tools
installer) — `cl.exe` must resolve, either by running from a "Developer
Command Prompt" or by calling `vcvarsall.bat` first. `pybind11` itself is
a dev dependency (see `requirements/requirements-dev.txt`).

```powershell
pip install -e cpp_inference_ext/
```

Verify it actually built and is importable:

```powershell
python -c "import cpp_inference; print(cpp_inference.linear_batched)"
```

If this import fails (compiler unavailable, build never run, wrong
Python ABI), `inference/exported_model.py` degrades silently to the
NumPy path — there's no error, no warning, just a small perf difference.
See `development/Problems.md` #32 for whether this accelerator measurably
helps in practice on this project's actual model sizes (small matrices —
the win, if any, is in per-call dispatch overhead, not raw FLOPs).
