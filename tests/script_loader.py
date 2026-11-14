"""Load a file under scripts/ as a module, and run one as `__main__` (V6.6.6, #359). scripts/ is not a package, and many
scripts import their siblings by bare name, so the folder of the script goes on sys.path first, as when it runs."""

from __future__ import annotations

import importlib.util
import runpy
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"


def load_script(relative: str):
    """`relative` is the path under scripts/ without `.py`, e.g. "render_lean_credentials" or "lean_smoke/exception_scope"."""
    path = SCRIPTS / f"{relative}.py"
    folder = str(path.parent)
    if folder not in sys.path:
        sys.path.insert(0, folder)
    name = "_script_" + relative.replace("/", "_")
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def run_script(relative: str, argv: list[str], monkeypatch) -> int | str | None:
    """Runs scripts/<relative>.py as `__main__` with `argv`; returns its exit code (None when it falls off the end)."""
    path = SCRIPTS / f"{relative}.py"
    monkeypatch.setattr(sys, "argv", [str(path), *argv])
    monkeypatch.syspath_prepend(str(path.parent))
    try:
        runpy.run_path(str(path), run_name="__main__")
    except SystemExit as exit_info:
        return exit_info.code
    return None



def block_path_writes(monkeypatch) -> list:
    """Records every `Path.write_text`, `Path.write_bytes` and `Path.mkdir` instead of doing it: for running a one-off
    script as `__main__` against the real tree without changing it. Returns the list of (method, path, args)."""
    writes: list = []
    for method in ("write_text", "write_bytes", "mkdir"):
        monkeypatch.setattr(Path, method, lambda self, *args, _method=method, **kwargs: writes.append((_method, self, args)))
    return writes


def fake_module(monkeypatch, name: str, **attributes):
    """Puts a stand-in for `name` in sys.modules, so a script run as `__main__` imports it instead of the real one."""
    import types

    module = types.ModuleType(name)
    for key, value in attributes.items():
        setattr(module, key, value)
    monkeypatch.setitem(sys.modules, name, module)
    return module


class Stop(Exception):
    """Raised by `stop_at_first_read`: the script got as far as its first file read."""


def stop_at_first_read(monkeypatch) -> None:
    """Makes `Path.read_text`/`read_bytes` raise `Stop`: running a one-off script as `__main__` reaches its entry point
    and then stops before it can read, and so before it can change, anything in the real tree."""

    def stop(self, *args, **kwargs):
        raise Stop(str(self))

    monkeypatch.setattr(Path, "read_text", stop)
    monkeypatch.setattr(Path, "read_bytes", stop)


STORED = ROOT / "tests" / "data" / "stored_rules"


def serve_stored_rules(monkeypatch, mapping: dict[str, str]) -> None:
    """`ml/evaluation/` is gitignored, so a clean checkout (CI) lacks the stored rule files some scripts read at import.
    For each `{path suffix: file under tests/data/stored_rules}` this serves the tracked copy when the real file is absent."""
    real_read_text, real_read_bytes, real_exists = Path.read_text, Path.read_bytes, Path.exists

    def stand_in(path: Path) -> Path | None:
        posix = path.as_posix()
        for suffix, name in mapping.items():
            if posix.endswith(suffix) and not real_exists(path):
                return STORED / name
        return None

    monkeypatch.setattr(Path, "read_text", lambda self, *args, **kwargs: real_read_text(stand_in(self) or self, *args, **kwargs))
    monkeypatch.setattr(Path, "read_bytes", lambda self: real_read_bytes(stand_in(self) or self))
    monkeypatch.setattr(Path, "exists", lambda self, **kwargs: real_exists(stand_in(self) or self, **kwargs))
