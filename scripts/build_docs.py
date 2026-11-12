"""Prepare the docs site (V6.6.5, #346): one API reference page per `aether_quant` facade, the nav that lists them, and the
tutorial notebooks copied into `docs/tutorials/` (gitignored there; `notebooks/` is the source).

    python scripts/build_docs.py            # write docs/reference/*.md, the mkdocs.yml nav block, docs/tutorials/*.ipynb
    python scripts/build_docs.py --check    # fail if a reference page or the nav is missing or stale (no writes)
    mkdocs build --strict                   # then the site, into site/
"""

from __future__ import annotations

import argparse
import importlib
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
DOCS = ROOT / "docs"
REFERENCE = DOCS / "reference"
TUTORIALS = DOCS / "tutorials"
MKDOCS = ROOT / "mkdocs.yml"
NAV_START, NAV_END = "      # AQ:REFERENCE_NAV_START (scripts/build_docs.py)\n", "      # AQ:REFERENCE_NAV_END\n"


def facades() -> list[str]:
    return sorted(path.stem for path in (ROOT / "aether_quant").glob("*.py") if not path.stem.startswith("_"))


def reference_page(name: str) -> str:
    module = importlib.import_module(f"aether_quant.{name}")
    summary = (module.__doc__ or "").strip().split("\n\n")[0].replace("\n", " ")
    members = "\n".join(f"        - {member}" for member in sorted(module.__all__))
    return (
        f"# aether_quant.{name}\n\n{summary}\n\n"
        f"::: aether_quant.{name}\n    options:\n      members:\n{members}\n"
    )


def nav_block() -> str:
    return NAV_START + "".join(f"      - aether_quant.{name}: reference/{name}.md\n" for name in facades()) + NAV_END


def expected_files() -> dict[Path, str]:
    return {REFERENCE / f"{name}.md": reference_page(name) for name in facades()}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    problems = []
    config = MKDOCS.read_text(encoding="utf-8")
    start, end = config.index(NAV_START), config.index(NAV_END) + len(NAV_END)
    if config[start:end] != nav_block():
        problems.append("mkdocs.yml: the API reference nav is stale")
        if not args.check:
            MKDOCS.write_text(config[:start] + nav_block() + config[end:], encoding="utf-8", newline="\n")
    for path, text in expected_files().items():
        if not path.exists() or path.read_text(encoding="utf-8") != text:
            problems.append(f"{path.relative_to(ROOT).as_posix()} is missing or stale")
            if not args.check:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text, encoding="utf-8", newline="\n")
    stray = sorted(set(REFERENCE.glob("*.md")) - set(expected_files()) - {REFERENCE / "index.md"})
    problems += [f"{path.relative_to(ROOT).as_posix()} documents no facade" for path in stray]
    if not args.check:
        TUTORIALS.mkdir(parents=True, exist_ok=True)
        for notebook in sorted((ROOT / "notebooks").glob("*.ipynb")):
            shutil.copyfile(notebook, TUTORIALS / notebook.name)
    if args.check:
        for problem in problems:
            print(problem, file=sys.stderr)
        return 1 if problems else 0
    print(f"docs ready: {len(expected_files())} reference pages, {len(list(TUTORIALS.glob('*.ipynb')))} tutorials")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
