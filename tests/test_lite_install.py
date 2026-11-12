"""`pip install aether-quant` with no extras is the research-only install (V6.6.5, #342): numpy and pandas only, and every
facade plus `aq --help` and `aq hello --offline` must work with every optional package blocked."""

from __future__ import annotations

import subprocess
import sys
import textwrap
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BLOCKED = (
    "httpx", "scipy", "sklearn", "pyarrow", "statsmodels", "torch", "redis", "psycopg", "psycopg2", "fastapi", "uvicorn", "starlette",
    "keyring", "ibapi", "lean", "matplotlib", "requests", "yaml", "dotenv", "flask", "joblib", "AlgorithmImports", "nbclient", "hypothesis",
)


def facade_modules() -> list[str]:
    return sorted(path.stem for path in (ROOT / "aether_quant").glob("*.py") if not path.stem.startswith("_"))


def _run_blocked(body: str) -> subprocess.CompletedProcess:
    script = textwrap.dedent(
        f"""
        import importlib.abc, sys
        BLOCKED = {BLOCKED!r}
        class Blocker(importlib.abc.MetaPathFinder):
            def find_spec(self, name, path=None, target=None):
                if name.split(".")[0] in BLOCKED:
                    raise ModuleNotFoundError(f"blocked in the lite install: {{name}}")
                return None
        sys.meta_path.insert(0, Blocker())
        sys.path.insert(0, {str(ROOT)!r})
        """
    ) + textwrap.dedent(body)
    return subprocess.run([sys.executable, "-c", script], cwd=ROOT, capture_output=True, text=True, timeout=600)


def test_base_dependencies_are_numpy_and_pandas_only():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    names = sorted(spec.split(">")[0].split("=")[0].split("[")[0].strip().lower() for spec in project["dependencies"])
    assert names == ["numpy", "pandas"]


def test_every_facade_imports_with_optional_packages_blocked():
    modules = facade_modules()
    result = _run_blocked(
        f"""
        import importlib
        for name in {modules!r}:
            importlib.import_module("aether_quant." + name)
        print("imported", len({modules!r}))
        """
    )
    assert result.returncode == 0, result.stderr[-4000:]


def test_aq_help_and_hello_offline_run_with_optional_packages_blocked(tmp_path):
    result = _run_blocked(
        f"""
        import os
        os.environ["AQ_SKIP_UPDATE_CHECK"] = "1"
        import aq_cli
        for argv in (["--help"], ["hello", "--offline", "--json", {str(tmp_path / "hello.json")!r}]):
            try:
                aq_cli.main(argv)
            except SystemExit as exit_:
                assert exit_.code in (0, None), (argv, exit_.code)
        """
    )
    assert result.returncode == 0, result.stderr[-4000:]
    assert "Sharpe" in result.stdout
