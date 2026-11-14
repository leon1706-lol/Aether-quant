"""scripts/build_docs.py (V6.6.6): the API reference pages and nav, checked or rebuilt, and the tutorials copied in, on a copy
of the docs tree."""

from __future__ import annotations

import shutil

import pytest

from script_loader import ROOT, load_script


@pytest.fixture
def docs(tmp_path, monkeypatch):
    module = load_script("build_docs")
    shutil.copyfile(ROOT / "mkdocs.yml", tmp_path / "mkdocs.yml")
    reference = tmp_path / "docs" / "reference"
    shutil.copytree(ROOT / "docs" / "reference", reference)
    (tmp_path / "aether_quant").mkdir()  # facades() lists the package's module names; the pages import the real modules
    for path in (ROOT / "aether_quant").glob("*.py"):
        (tmp_path / "aether_quant" / path.name).write_text("", encoding="utf-8")
    (tmp_path / "notebooks").mkdir()
    (tmp_path / "notebooks" / "00_x.ipynb").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module, "MKDOCS", tmp_path / "mkdocs.yml")
    monkeypatch.setattr(module, "REFERENCE", reference)
    monkeypatch.setattr(module, "TUTORIALS", tmp_path / "docs" / "tutorials")
    return module, reference, tmp_path


def test_a_current_tree_passes_the_check(docs):
    module, _reference, _root = docs
    assert module.main(["--check"]) == 0


def test_stale_nav_missing_and_stray_pages_are_reported_then_rebuilt(docs, capsys):
    module, reference, root = docs
    text = (root / "mkdocs.yml").read_text(encoding="utf-8")
    first = next(iter(module.expected_files()))
    (root / "mkdocs.yml").write_text(text.replace(f"reference/{first.stem}.md", "reference/gone.md"), encoding="utf-8")
    (reference / first.name).unlink()
    (reference / "orphan.md").write_text("x", encoding="utf-8")
    assert module.main(["--check"]) == 1
    err = capsys.readouterr().err
    assert "nav is stale" in err and f"{first.name} is missing or stale" in err and "orphan.md documents no facade" in err
    assert module.main([]) == 0
    assert (reference / first.name).exists() and (root / "docs" / "tutorials" / "00_x.ipynb").exists() and "docs ready" in capsys.readouterr().out
    (reference / "orphan.md").unlink()
    assert module.main(["--check"]) == 0
