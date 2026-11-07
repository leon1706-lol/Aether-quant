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
