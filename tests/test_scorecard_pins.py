"""scripts/scorecard_pins.py (V6.6.7, #361): Scorecard's Pinned-Dependencies rules, offline, and the repo clean under them."""

from __future__ import annotations

import pytest

from script_loader import load_script, run_script

pins = load_script("scorecard_pins")


@pytest.mark.parametrize(("command", "pinned"), [
    ("pip install --require-hashes -r requirements/lock/ci.txt", True),
    ("python -m pip install -r reqs.txt --require-hashes", True),
    ("pip install --no-deps -e .", True),
    ("pip install --no-deps -e git+https://github.com/a/b.git@" + "a" * 40 + "#egg=b", True),
    ("pip install --no-deps dist/aq-1.0-py3-none-any.whl", True),
    ("/tmp/venv/bin/pip install dist/*.whl", True),
    ("pip install -r requirements.txt", False),
    ("pip install --upgrade pip", False),
    ("pip install .", False),
    ("pip install -e .", False),
    ("pip install --no-deps -e git+https://github.com/a/b.git@main", False),
    ("pip install ruff==0.16.4", False),
    ("python3 -m pip install torch --index-url https://download.pytorch.org/whl/cpu", False),
    ("pip install --no-cache-dir", False),
])
def test_pip_rules(command, pinned):
    argv = pins.commands(command)[0]
    args = pins.pip_install_args(argv)
    assert args is not None
    assert pins.is_pinned_pip(args) is pinned


def test_non_pip_commands_and_npm():
    assert pins.pip_install_args(["pip", "list"]) is None and pins.pip_install_args([]) is None
    assert pins.pip_install_args(["python", "-m", "venv", "x"]) is None
    assert pins.is_pinned_npm(["npm", "ci"]) is True
    assert pins.is_pinned_npm(["npm", "install", "x@1"]) is False
    assert pins.is_pinned_npm(["npm", "run", "build"]) is None and pins.is_pinned_npm(["npx", "tsc"]) is None


def test_commands_split_operators_and_drop_prefixes():
    assert pins.commands("sudo FOO=1 pip install x && npm ci; echo hi # pip install y") == [["pip", "install", "x"], ["npm", "ci"], ["echo", "hi"]]
    assert pins.commands("# only a comment") == []
    assert pins.commands("pip install 'unclosed") == [["pip", "install", "'unclosed"]]


def test_join_continuations_keeps_the_first_line_number():
    assert pins.join_continuations("a \\\n  b\nc\nd \\") == [(1, "a    b"), (3, "c"), (4, "d  ")]


def test_shell_findings_and_pipe_to_shell():
    text = "pip install x\nnpm install\ncurl -sSL https://x/install.sh | sudo bash\nwget -qO- u | sh\ncurl -o f u | tee f\n"
    kinds = [(f.line, f.kind) for f in pins.shell_findings("s.sh", text)]
    assert kinds == [(1, "pip"), (2, "npm"), (3, "download-pipe-shell"), (4, "download-pipe-shell")]
    assert str(pins.Finding("a", 1, "pip", "x")) == "a:1: pip: x"


def test_workflow_findings():
    text = (
        "jobs:\n  a:\n    steps:\n"
        "      - uses: actions/checkout@" + "b" * 40 + " # v1\n"
        "      - uses: ./local\n"
        "      - uses: docker://alpine@sha256:" + "c" * 64 + "\n"
        "      - uses: owner/action@v2\n"
        "      - run: |\n          echo start\n          pip install foo\n"
        "      - name: no run\n"
        "  b:\n    uses: org/repo/.github/workflows/x.yml@v1\n"
    )
    found = [(f.kind, f.text) for f in pins.workflow_findings("w.yml", text)]
    assert ("action", "owner/action@v2") in found and ("action", "org/repo/.github/workflows/x.yml@v1") in found
    assert ("pip", "pip install foo") in found and len(found) == 3
    assert pins.workflow_findings("e.yml", "") == []
    assert pins._line_of(["x"], "\n") == 1


def test_dockerfile_findings():
    text = (
        "ARG BASE=python:3.11@sha256:" + "d" * 64 + "\n"
        "FROM ${BASE} AS build\n"
        "FROM build\n"
        "FROM scratch\n"
        "FROM --platform=linux/amd64 node:20\n"
        "# FROM ignored\n"
        "RUN pip install --require-hashes -r r.txt \\\n    && pip install x\n"
        "RUN npm ci\n"
        "ARG NOVALUE\n"
        "\n"
    )
    found = [(f.line, f.kind, f.text) for f in pins.dockerfile_findings("Dockerfile", text)]
    assert found == [(5, "image", "node:20"), (7, "pip", "pip install x")]


def test_file_classification():
    assert pins.is_shell_script("a/b.sh", "") and pins.is_shell_script("run", "#!/usr/bin/env bash")
    assert pins.is_shell_script("run", "#!/bin/sh -e") and not pins.is_shell_script("run", "#!/usr/bin/env python3")
    assert not pins.is_shell_script("notes", "plain text")
    assert pins.is_dockerfile("Dockerfile.lean") and pins.is_dockerfile("docker/app.Dockerfile")
    assert not pins.is_dockerfile("dockerfile_helpers.py") and not pins.is_dockerfile("Dockerfile.md")


def test_scan_over_a_tree(tmp_path):
    (tmp_path / ".github" / "workflows").mkdir(parents=True)
    (tmp_path / ".github" / "workflows" / "ci.yml").write_text("jobs:\n  a:\n    steps:\n      - run: pip install x\n", encoding="utf-8")
    (tmp_path / "Dockerfile").write_text("FROM alpine\n", encoding="utf-8")
    (tmp_path / "go.sh").write_text("npm install\n", encoding="utf-8")
    (tmp_path / "tool").write_text("#!/bin/bash\npip install y\n", encoding="utf-8")
    (tmp_path / "README").write_text("pip install z\n", encoding="utf-8")
    (tmp_path / "big.sh").write_bytes(b"#" * 2_000_001)
    paths = [".github/workflows/ci.yml", "Dockerfile", "go.sh", "tool", "README", "big.sh", "missing.sh", "data.json"]
    found = sorted((f.path, f.kind) for f in pins.scan(tmp_path, paths))
    assert found == [(".github/workflows/ci.yml", "pip"), ("Dockerfile", "image"), ("go.sh", "npm"), ("tool", "pip")]


def test_repo_has_no_unpinned_dependency():
    found = pins.scan()
    assert not found, "\n".join(map(str, found))


def test_main_reports_and_exits(monkeypatch, capsys):
    assert run_script("scorecard_pins", [], monkeypatch) == 0
    assert "0 unpinned" in capsys.readouterr().out
    monkeypatch.setattr(pins, "scan", lambda: [pins.Finding("x.sh", 3, "pip", "pip install y")])
    assert pins.main([]) == 1
    captured = capsys.readouterr()
    assert "x.sh:3: pip: pip install y" in captured.out and "1 unpinned" in captured.err
