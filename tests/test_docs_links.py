"""Docs link/marker guard (V5.5.0 CI): every relative Markdown link in the
tracked docs must resolve, and every auto-generated README block must have a
matching start/end marker. The README alone carries ~55 relative links plus a
dozen `AQ:*` blocks that `aq test`/`aq evaluate`/`aq backtest` rewrite in
place; a renamed file or a half-deleted marker otherwise rots silently until
a human clicks it (or the next generator run mangles the page).

Conventions match the rest of this repo: no test classes, module-level
helpers. Skips cleanly outside a git checkout (an sdist has no `git ls-files`)."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

# Frozen snapshots and generated mirrors: not maintained as live docs.
EXCLUDED_PREFIXES = (
    "Aether-quant-Obsidian-Vault/",
    "development/backups/",
    "backtests/",
    "webui/node_modules/",
)

_LINK_RE = re.compile(r"(?<!\!)\[[^\]\n]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
_IMAGE_RE = re.compile(r"!\[[^\]\n]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
_MARKER_RE = re.compile(r"<!--\s*(AQ:[A-Z0-9_]+?)_(START|END)\s*-->")
_FENCE_RE = re.compile(r"^(```|~~~)")


def _tracked_markdown() -> list[Path]:
    try:
        output = subprocess.run(
            ["git", "ls-files", "*.md"], cwd=ROOT, capture_output=True, text=True, check=True, timeout=30
        ).stdout
    except (OSError, subprocess.SubprocessError):
        pytest.skip("not a git checkout")
    paths = [ROOT / line for line in output.splitlines() if line and not line.startswith(EXCLUDED_PREFIXES)]
    return [path for path in paths if path.exists()]  # a file deleted in the working tree is not a docs bug


def _strip_fenced_code(text: str) -> str:
    kept: list[str] = []
    in_fence = False
    for line in text.splitlines():
        if _FENCE_RE.match(line.strip()):
            in_fence = not in_fence
            continue
        if not in_fence:
            kept.append(re.sub(r"`[^`\n]*`", "", line))  # inline code can contain link-looking text
    return "\n".join(kept)


def _is_external(target: str) -> bool:
    return target.startswith(("http://", "https://", "mailto:", "#", "tel:", "data:")) or "://" in target


def _is_gitignored(path: Path) -> bool:
    """A link into a gitignored path resolves locally but 404s on a fresh clone / CI checkout."""
    try:
        relative = path.relative_to(ROOT)
    except ValueError:
        return False
    try:
        return subprocess.run(["git", "check-ignore", "-q", str(relative)], cwd=ROOT, timeout=30).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _broken_links(path: Path) -> list[str]:
    text = _strip_fenced_code(path.read_text(encoding="utf-8", errors="replace"))
    broken = []
    for target in _LINK_RE.findall(text) + _IMAGE_RE.findall(text):
        if _is_external(target):
            continue
        relative = target.split("#", 1)[0].split("?", 1)[0]
        if not relative:
            continue
        resolved = (path.parent / relative).resolve() if not relative.startswith("/") else (ROOT / relative.lstrip("/"))
        if not resolved.exists() or _is_gitignored(resolved):
            broken.append(f"{path.relative_to(ROOT)} -> {target}")
    return broken


def test_every_relative_markdown_link_resolves():
    broken = [problem for path in _tracked_markdown() for problem in _broken_links(path)]
    assert not broken, "broken relative links:\n" + "\n".join(sorted(broken))


def test_every_generated_block_marker_is_paired_exactly_once_per_file():
    problems = []
    for path in _tracked_markdown():
        text = path.read_text(encoding="utf-8", errors="replace")
        counts: dict[str, dict[str, int]] = {}
        for name, kind in _MARKER_RE.findall(text):
            counts.setdefault(name, {"START": 0, "END": 0})[kind] += 1
        for name, pair in counts.items():
            if pair["START"] != pair["END"]:
                problems.append(f"{path.relative_to(ROOT)}: {name} has {pair['START']} START / {pair['END']} END")
    assert not problems, "\n".join(problems)


def test_the_link_checker_itself_catches_a_broken_link_and_ignores_code(tmp_path):
    doc = tmp_path / "doc.md"
    (tmp_path / "real.md").write_text("x", encoding="utf-8")
    doc.write_text(
        "[ok](real.md) [anchor](real.md#top) [web](https://example.com) [self](#here)\n"
        "[broken](missing.md) ![img](nope.png)\n"
        "`[inline](not-a-link.md)`\n"
        "```text\n[fenced](also-not-a-link.md)\n```\n",
        encoding="utf-8",
    )
    # _broken_links reports paths relative to ROOT, so exercise the parser pieces directly
    text = _strip_fenced_code(doc.read_text(encoding="utf-8"))
    targets = [t for t in _LINK_RE.findall(text) + _IMAGE_RE.findall(text) if not _is_external(t)]
    assert sorted(targets) == ["missing.md", "nope.png", "real.md", "real.md#top"]
    assert [t for t in targets if not (tmp_path / t.split("#")[0]).exists()] == ["missing.md", "nope.png"]
