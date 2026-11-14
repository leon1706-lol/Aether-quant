"""The tutorials' percent-format sources run as plain Python too (V6.6.6, #359): every line, the Colab install branch included.

tests/test_notebooks.py runs the built notebooks in a Jupyter kernel, where coverage can't see the source files. Here each
source runs with `runpy`, from the checkout and on the matplotlib Agg backend.
"""

from __future__ import annotations

import runpy
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SOURCES = sorted((ROOT / "notebooks" / "src").glob("*.py"))


@pytest.fixture(autouse=True)
def _headless(monkeypatch):
    import matplotlib

    matplotlib.use("Agg")
    monkeypatch.chdir(ROOT / "notebooks")
    yield
    import matplotlib.pyplot as plt

    plt.close("all")


def test_there_are_four_sources():
    assert [path.stem for path in SOURCES] == ["00_hello_world", "01_signal_evaluation", "02_book_construction", "03_overfitting_tests"]


@pytest.mark.parametrize("source", SOURCES, ids=lambda path: path.stem)
def test_each_source_runs_end_to_end_from_the_checkout(source, capsys):
    namespace = runpy.run_path(str(source), run_name="__main__")
    assert str(ROOT) in sys.path
    assert namespace, "the tutorial defined nothing"
    assert "Traceback" not in capsys.readouterr().err


class _InstallSeen(Exception):
    pass


@pytest.mark.parametrize("source", SOURCES, ids=lambda path: path.stem)
def test_on_colab_the_first_cell_installs_the_latest_library(source, monkeypatch):
    magics = []

    def run_line_magic(name, line):
        magics.append((name, line))
        raise _InstallSeen  # the rest of the tutorial is the plain run above

    monkeypatch.setitem(sys.modules, "google.colab", types.ModuleType("google.colab"))
    with pytest.raises(_InstallSeen):
        runpy.run_path(str(source), init_globals={"get_ipython": lambda: types.SimpleNamespace(run_line_magic=run_line_magic)})
    assert magics == [("pip", 'install -q "aether-quant[notebooks]"')], "no version floor: Colab installs PyPI's latest"
