"""scripts/build_notebooks.py's runtime (V6.6.6, #359): building a notebook from its percent source, running it, and the check, execute and plain write modes of `main()`.
nbformat and nbclient are stood in, so the file runs where the `notebooks` extra is not installed (CI's python-tests job)."""

from __future__ import annotations

import json
import sys
import types
from types import SimpleNamespace

import pytest

from script_loader import load_script

SOURCE = "# %% [markdown]\n# # Title\n#\n# text\n\n# %%\nx = 1\n"


class FakeClient:
    fail = False

    def __init__(self, notebook, timeout, kernel_name, resources):
        self.notebook, self.resources = notebook, resources

    def execute(self):
        if FakeClient.fail:
            raise RuntimeError("x" * 2000 + " cell failed")
        for cell in self.notebook.cells:
            cell.setdefault("metadata", {})["execution"] = {"started": "now"}


def _install(monkeypatch):
    nbformat = types.ModuleType("nbformat")

    def new_notebook():
        return SimpleNamespace(cells=[], metadata={})

    def new_cell(kind):
        return lambda source: {"cell_type": kind, "source": source, "metadata": {}}

    nbformat.v4 = SimpleNamespace(new_notebook=new_notebook, new_markdown_cell=new_cell("markdown"), new_code_cell=new_cell("code"))
    nbformat.write = lambda notebook, path: path.write_text(json.dumps({"cells": notebook.cells, "metadata": notebook.metadata}), encoding="utf-8")
    nbformat.read = lambda path, as_version: SimpleNamespace(**json.loads(path.read_text(encoding="utf-8")))
    nbclient = types.ModuleType("nbclient")
    nbclient.NotebookClient = FakeClient
    monkeypatch.setitem(sys.modules, "nbformat", nbformat)
    monkeypatch.setitem(sys.modules, "nbclient", nbclient)
    FakeClient.fail = False


@pytest.fixture
def module(monkeypatch, tmp_path):
    _install(monkeypatch)
    builder = load_script("build_notebooks")
    sources = tmp_path / "notebooks" / "src"
    sources.mkdir(parents=True)
    (sources / "00_first.py").write_text(SOURCE, encoding="utf-8")
    (sources / "01_second.py").write_text("# %%\ny = 2\n", encoding="utf-8")
    for name, value in (("ROOT", tmp_path), ("SOURCES", sources), ("OUT", tmp_path / "notebooks")):
        monkeypatch.setattr(builder, name, value)
    return builder


def test_markdown_cells_lose_their_comment_marker_and_empty_cells_are_dropped(module):
    cells = module.parse_percent("ignored line\n# %% [markdown]\n# # Title\n#\n# text\n#plain\n\n# %%\nx = 1\n\n# %%\n\n")
    assert cells == [("markdown", "# Title\n\ntext\nplain"), ("code", "x = 1")]


def test_a_notebook_has_fixed_cell_ids_and_the_python_kernel(module, tmp_path):
    notebook = module.build_notebook(tmp_path / "notebooks" / "src" / "00_first.py")
    assert [cell["id"] for cell in notebook.cells] == ["00_first-00", "00_first-01"] and notebook.metadata["kernelspec"]["name"] == "python3"
    assert module.cells_of(notebook) == [("markdown", "# Title\n\ntext"), ("code", "x = 1")]


def test_executing_a_notebook_stores_outputs_without_execution_timestamps(module, tmp_path):
    notebook = module.build_notebook(tmp_path / "notebooks" / "src" / "00_first.py")
    ran = module.execute(notebook, tmp_path)
    assert all("execution" not in cell["metadata"] for cell in ran.cells)


def test_a_plain_run_writes_every_notebook_and_executes_them_on_request(module, tmp_path, capsys):
    (tmp_path / "notebooks" / "stale.ipynb_checkpoints").mkdir()
    assert module.main([]) == 0
    assert (tmp_path / "notebooks" / "00_first.ipynb").exists() and (tmp_path / "notebooks" / "01_second.ipynb").exists() and not (tmp_path / "notebooks" / "stale.ipynb_checkpoints").exists()
    assert module.main(["--execute", "--only", "00_first"]) == 0 and "ran in" in capsys.readouterr().out


def test_the_check_compares_the_tracked_notebook_with_its_source(module, tmp_path, capsys):
    assert module.main(["--check"]) == 1 and "00_first.ipynb missing" in capsys.readouterr().err
    module.main([])
    capsys.readouterr()
    assert module.main(["--check"]) == 0
    (tmp_path / "notebooks" / "src" / "00_first.py").write_text("# %%\nx = 99\n", encoding="utf-8")
    assert module.main(["--check", "--only", "00_first"]) == 1 and "differs from" in capsys.readouterr().err


def test_a_check_with_execute_runs_each_notebook_and_reports_every_failure(module, tmp_path, capsys):
    module.main([])
    capsys.readouterr()
    assert module.main(["--check", "--execute"]) == 0 and capsys.readouterr().out.count("ran in") == 2
    FakeClient.fail = True
    assert module.main(["--check", "--execute"]) == 1 and "cell failed" in capsys.readouterr().err
    (tmp_path / "notebooks" / "src").rename(tmp_path / "notebooks" / "elsewhere")
    monkey_sources = tmp_path / "notebooks" / "elsewhere"
    module.SOURCES = monkey_sources
    FakeClient.fail = False
    assert module.main(["--check", "--execute"]) == 0
