"""Build the tutorial notebooks from their percent-format sources (V6.6.5, #343).

`notebooks/src/NN_name.py` is the source of truth: `# %%` starts a code cell, `# %% [markdown]` a markdown cell whose
lines lose their leading `# `. The notebook is written to `notebooks/NN_name.ipynb` with fixed cell ids and no
timestamps, so a rebuild only changes what changed. `--execute` runs each one with nbclient (from `notebooks/`, offline:
the notebooks read the bundled sample) and stores the outputs, which is what GitHub and Colab show.

    python scripts/build_notebooks.py --execute          # rebuild and run all four (about 3 minutes on a small PC)
    python scripts/build_notebooks.py --check            # the .ipynb cells match their sources (no execution)
    python scripts/build_notebooks.py --check --execute  # also run them in a temp dir and fail on any error (CI)
"""

from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ROOT / "notebooks" / "src"
OUT = ROOT / "notebooks"


def parse_percent(text: str) -> list[tuple[str, str]]:
    """[(cell_type, source)] from a percent-format script."""
    cells: list[tuple[str, list[str]]] = []
    for line in text.splitlines():
        if line.startswith("# %%"):
            cells.append(("markdown" if "[markdown]" in line else "code", []))
            continue
        if not cells:
            continue
        kind, lines = cells[-1]
        if kind == "markdown":
            lines.append(line[2:] if line.startswith("# ") else line.lstrip("#"))
        else:
            lines.append(line)
    out = []
    for kind, lines in cells:
        source = "\n".join(lines).strip("\n")
        if source:
            out.append((kind, source))
    return out


def build_notebook(source_path: Path):
    import nbformat

    notebook = nbformat.v4.new_notebook()
    notebook.metadata = {
        "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
        "language_info": {"name": "python"},
        "colab": {"provenance": []},
    }
    for index, (kind, source) in enumerate(parse_percent(source_path.read_text(encoding="utf-8"))):
        cell = nbformat.v4.new_markdown_cell(source) if kind == "markdown" else nbformat.v4.new_code_cell(source)
        cell["id"] = f"{source_path.stem}-{index:02d}"
        notebook.cells.append(cell)
    return notebook


def execute(notebook, workdir: Path, timeout: int = 900):
    from nbclient import NotebookClient

    client = NotebookClient(notebook, timeout=timeout, kernel_name="python3", resources={"metadata": {"path": str(workdir)}})
    client.execute()
    for cell in notebook.cells:
        cell.get("metadata", {}).pop("execution", None)
    return notebook


def cells_of(notebook) -> list[tuple[str, str]]:
    return [(cell["cell_type"], cell["source"]) for cell in notebook.cells]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="Compare the tracked .ipynb cells with their sources; write nothing")
    parser.add_argument("--execute", action="store_true", help="Run every notebook (with --check: in a temp dir, outputs discarded)")
    parser.add_argument("--only", default=None, help="Build one notebook by stem, e.g. 01_signal_evaluation")
    args = parser.parse_args(argv)
    import nbformat

    sources = sorted(SOURCES.glob("*.py"))
    if args.only:
        sources = [path for path in sources if path.stem == args.only]
    problems: list[str] = []
    for source in sources:
        target = OUT / f"{source.stem}.ipynb"
        built = build_notebook(source)
        if args.check:
            if not target.exists():
                problems.append(f"{target.name} missing: run python scripts/build_notebooks.py --execute")
            elif cells_of(nbformat.read(target, as_version=4)) != cells_of(built):
                problems.append(f"{target.name} differs from {source.relative_to(ROOT)}: run python scripts/build_notebooks.py --execute")
            if args.execute:
                with tempfile.TemporaryDirectory() as scratch:
                    began = time.perf_counter()
                    try:
                        execute(built, OUT if (OUT / "src").is_dir() else Path(scratch))
                        print(f"{source.stem}: ran in {time.perf_counter() - began:.0f} s")
                    except Exception as error:  # noqa: BLE001 - report every failing notebook
                        problems.append(f"{source.stem}: {type(error).__name__}: {str(error)[-1500:]}")
            continue
        if args.execute:
            began = time.perf_counter()
            execute(built, OUT)
            print(f"{source.stem}: ran in {time.perf_counter() - began:.0f} s")
        nbformat.write(built, target)
        print(f"wrote {target.relative_to(ROOT)}")
    for leftover in OUT.glob("*.ipynb_checkpoints"):
        shutil.rmtree(leftover, ignore_errors=True)
    for problem in problems:
        print(problem, file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
