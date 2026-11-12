"""The documentation site (V6.6.5, #346): every facade has a reference page, every nav entry exists, the guide's examples
run, and the generated blocks have their markers. CI's `docs` job builds it with `mkdocs build --strict`; set
AQ_BUILD_DOCS=1 to build it here too."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
CODE = re.compile(r"```python\n(.*?)```", re.S)


def test_reference_pages_and_nav_match_the_facades():
    result = subprocess.run([sys.executable, str(ROOT / "scripts" / "build_docs.py"), "--check"], capture_output=True, text=True, timeout=300)
    assert result.returncode == 0, result.stderr
    facades = sorted(path.stem for path in (ROOT / "aether_quant").glob("*.py") if not path.stem.startswith("_"))
    assert sorted(path.stem for path in (DOCS / "reference").glob("*.md") if path.stem != "index") == facades


def test_every_nav_page_exists():
    config = (ROOT / "mkdocs.yml").read_text(encoding="utf-8")
    pages = re.findall(r":\s+([\w/.-]+\.(?:md|ipynb))\s*$", config, re.M)
    assert len(pages) > 40
    missing = [page for page in pages if not (DOCS / page).exists() and not (page.startswith("tutorials/") and (ROOT / "notebooks" / Path(page).name).exists())]
    assert not missing, missing


@pytest.mark.parametrize("page", sorted((DOCS / "guide").glob("*.md")), ids=lambda path: path.stem)
def test_every_guide_example_runs(page, monkeypatch):
    blocks = CODE.findall(page.read_text(encoding="utf-8"))
    assert blocks, f"{page.name} has no runnable example"
    monkeypatch.syspath_prepend(str(ROOT))
    for block in blocks:
        exec(compile(block, str(page), "exec"), {"__name__": "__docs__"})  # noqa: S102 - the docs' own examples


def test_generated_blocks_have_their_markers():
    text = (DOCS / "live" / "paper-to-live.md").read_text(encoding="utf-8")
    assert "<!-- AQ:READINESS_START -->" in text and "<!-- AQ:READINESS_END -->" in text
    assert "NOT READY" in text  # until a paper period, a forward record and a broker exist, the published scorecard says so


@pytest.mark.skipif(os.environ.get("AQ_BUILD_DOCS") != "1", reason="set AQ_BUILD_DOCS=1 (needs the docs extra); CI's docs job builds the site")
def test_the_site_builds_strictly(tmp_path):
    subprocess.run([sys.executable, str(ROOT / "scripts" / "build_docs.py")], check=True, timeout=300)
    result = subprocess.run([sys.executable, "-m", "mkdocs", "build", "--strict", "--site-dir", str(tmp_path / "site")], cwd=ROOT, capture_output=True, text=True, timeout=900)
    assert result.returncode == 0, result.stdout[-3000:] + result.stderr[-3000:]
