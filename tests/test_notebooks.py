"""The tutorial notebooks (V6.6.5, #343): each .ipynb matches its source, opens in Colab, was run, and holds no error.
CI's `notebooks` job runs them again (`scripts/build_notebooks.py --check --execute`); set AQ_RUN_NOTEBOOKS=1 to do it here."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SOURCES = sorted((ROOT / "notebooks" / "src").glob("*.py"))
COLAB = "https://colab.research.google.com/github/leon1706-lol/Aether-quant/blob/main/notebooks/{name}.ipynb"


def _load_builder():
    spec = importlib.util.spec_from_file_location("build_notebooks", ROOT / "scripts" / "build_notebooks.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_there_are_four_tutorials():
    assert [path.stem for path in SOURCES] == ["00_hello_world", "01_signal_evaluation", "02_book_construction", "03_overfitting_tests"]


@pytest.mark.parametrize("source", SOURCES, ids=lambda path: path.stem)
def test_each_notebook_matches_its_source(source):
    builder = _load_builder()
    notebook = json.loads((ROOT / "notebooks" / f"{source.stem}.ipynb").read_text(encoding="utf-8"))
    tracked = [(cell["cell_type"], "".join(cell["source"]) if isinstance(cell["source"], list) else cell["source"]) for cell in notebook["cells"]]
    assert tracked == builder.parse_percent(source.read_text(encoding="utf-8")), f"run python scripts/build_notebooks.py --execute --only {source.stem}"


@pytest.mark.parametrize("source", SOURCES, ids=lambda path: path.stem)
def test_each_notebook_opens_in_colab_installs_itself_and_was_run_clean(source):
    notebook = json.loads((ROOT / "notebooks" / f"{source.stem}.ipynb").read_text(encoding="utf-8"))
    text = lambda cell: "".join(cell["source"]) if isinstance(cell["source"], list) else cell["source"]  # noqa: E731
    assert COLAB.format(name=source.stem) in text(notebook["cells"][0])
    setup = text(notebook["cells"][1])
    assert '"google.colab" in sys.modules' in setup and "aether-quant[notebooks]" in setup
    code = [cell for cell in notebook["cells"] if cell["cell_type"] == "code"]
    assert all(cell.get("execution_count") for cell in code), "every code cell has run"
    assert not [output for cell in code for output in cell.get("outputs", []) if output.get("output_type") == "error"]
    assert notebook["metadata"]["kernelspec"]["name"] == "python3"


def test_the_readme_links_every_notebook_to_colab():
    readme = (ROOT / "notebooks" / "README.md").read_text(encoding="utf-8")
    for source in SOURCES:
        assert COLAB.format(name=source.stem) in readme


def test_the_builder_parses_percent_cells():
    builder = _load_builder()
    cells = builder.parse_percent("# %% [markdown]\n# # Title\n#\n# text\n\n# %%\nx = 1\n\n\n# %%\n\n")
    assert cells == [("markdown", "# Title\n\ntext"), ("code", "x = 1")]


@pytest.mark.skipif(os.environ.get("AQ_RUN_NOTEBOOKS") != "1", reason="set AQ_RUN_NOTEBOOKS=1 (about 4 minutes); CI's notebooks job runs them")
def test_every_notebook_runs():
    result = subprocess.run([sys.executable, str(ROOT / "scripts" / "build_notebooks.py"), "--check", "--execute"], capture_output=True, text=True, timeout=3600)
    assert result.returncode == 0, result.stdout[-2000:] + result.stderr[-4000:]
