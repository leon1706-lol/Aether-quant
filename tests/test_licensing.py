"""The license split (V6.6.5, #347): everything the wheel ships is Apache-2.0, the trading system is PolyForm
Noncommercial, and the metadata, LICENSE, NOTICE and REUSE.toml agree."""

from __future__ import annotations

import fnmatch
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _annotations() -> list[dict]:
    return tomllib.loads((ROOT / "REUSE.toml").read_text(encoding="utf-8"))["annotations"]


def license_of(relative: str) -> str:
    """The last matching REUSE annotation wins (the default comes first)."""
    found = ""
    for annotation in _annotations():
        patterns = annotation["path"] if isinstance(annotation["path"], list) else [annotation["path"]]
        if any(fnmatch.fnmatch(relative, pattern) or (pattern.endswith("/**") and relative.startswith(pattern[:-2])) for pattern in patterns):
            found = annotation["SPDX-License-Identifier"]
    return found


def _wheel_files() -> list[str]:
    tool = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["tool"]["setuptools"]
    files = [f"{name}.py" for name in tool["py-modules"]]
    for package in tool["packages"]:
        files += [path.relative_to(ROOT).as_posix() for path in (ROOT / package).rglob("*") if path.is_file() and "__pycache__" not in path.parts]
    return files


def test_everything_the_wheel_ships_is_apache():
    files = _wheel_files()
    assert len(files) > 300
    assert not [name for name in files if license_of(name) != "Apache-2.0"]


def test_the_trading_system_stays_noncommercial():
    for name in ("main.py", "train.py", "config.json", "scripts/forward_ledger.py", "ml/target_weights.csv", "development/Changelog.md", "Dockerfile.lean"):
        assert license_of(name) == "LicenseRef-PolyForm-Noncommercial-1.0.0", name
    for name in ("webui/src/App.tsx", "notebooks/00_hello_world.ipynb", "docs/index.md", "formal/AetherFormal/Authorize.lean", "Dockerfile"):
        assert license_of(name) == "Apache-2.0", name


def test_metadata_license_files_and_notice_agree():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert project["license"] == "Apache-2.0" and project["license-files"] == ["LICENSES/Apache-2.0.txt", "NOTICE"]
    assert not [c for c in project.get("classifiers", []) if c.startswith("License ::")]  # PEP 639: the expression, no classifier
    apache = (ROOT / "LICENSES" / "Apache-2.0.txt").read_text(encoding="utf-8")
    assert "Version 2.0, January 2004" in apache and "END OF TERMS AND CONDITIONS" in apache
    assert "PolyForm Noncommercial License 1.0.0" in (ROOT / "LICENSES" / "PolyForm-Noncommercial-1.0.0.txt").read_text(encoding="utf-8")
    top = (ROOT / "LICENSE").read_text(encoding="utf-8")
    assert "Apache License 2.0" in top and "PolyForm Noncommercial License 1.0.0" in top and "6.6.4" in top
    assert "Leon Schwarzkopf" in (ROOT / "NOTICE").read_text(encoding="utf-8")


def test_every_shipped_package_is_named_in_the_license_map():
    tool = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["tool"]["setuptools"]
    text = (ROOT / "LICENSE").read_text(encoding="utf-8")
    words = set(re.findall(r"[\w.]+", text))
    assert set(tool["packages"]) - {"aether_quant"} <= words | {"aether_quant"}
    assert {f"{name}.py" for name in tool["py-modules"]} <= words
