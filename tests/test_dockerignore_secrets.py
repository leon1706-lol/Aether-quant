"""Pins that .dockerignore keeps every secret file out of the image build context.

This exists because the gap it guards was real and shipped-adjacent: the engine
image does `COPY . .` and that same fat image is published to ghcr, so anything
not excluded here is baked into a PUBLIC registry layer - recoverable via
`docker history`/`docker save` even after a later commit removes it. Being
`.gitignore`'d does not help: it is a separate mechanism, and `lean.json` is
git-tracked on purpose anyway.

The bug this caught during the V2-22 security review (development/Problems.md
#42): `lean.live.json` - the rendered file that holds the REAL broker
credentials - was gitignored but NOT dockerignored, so `aq render-lean-config`
followed by `aq docker build` would have embedded a live broker password in the
published image. A literal line-grep over .dockerignore misses this class of
bug (patterns like `.env.*` cover `.env.live` without an exact line), so this
test evaluates real Docker pattern semantics instead.
"""

import fnmatch
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
DOCKERIGNORE = REPO_ROOT / ".dockerignore"

# Files that must NEVER reach the image build context.
SECRET_FILES = [
    "lean.json",          # tracked, but a locally-populated copy must not leak
    "lean.live.json",     # rendered by `aq render-lean-config` - holds real keys
    "lean.local.json",
    ".env",
    ".env.live",
    ".env.compose",
    "ib_config.py",
    "config.local.json",
    "server.key",
    "cert.pem",
]

# Files that must still reach the image (templates and real source).
REQUIRED_FILES = [
    ".env.live.example",
    ".env.compose.example",
    "config.json",
    "main.py",
]


def _load_rules() -> tuple[list[str], list[str]]:
    patterns: list[str] = []
    negations: list[str] = []
    for raw in DOCKERIGNORE.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        (negations if line.startswith("!") else patterns).append(line.lstrip("!"))
    return patterns, negations


def _is_excluded(path: str) -> bool:
    """Approximates Docker's .dockerignore matching (filepath.Match + `!`
    re-include, last-match-wins simplified to "any negation re-includes")."""
    patterns, negations = _load_rules()
    matched = any(fnmatch.fnmatch(path, p) or path == p for p in patterns)
    re_included = any(fnmatch.fnmatch(path, n) or path == n for n in negations)
    return matched and not re_included


@pytest.mark.parametrize("secret_file", SECRET_FILES)
def test_secret_file_is_excluded_from_image(secret_file):
    assert _is_excluded(secret_file), (
        f"{secret_file} would be COPY-ed into the published engine image. "
        f"Add it to .dockerignore's 'Local secrets' block."
    )


@pytest.mark.parametrize("required_file", REQUIRED_FILES)
def test_required_file_still_reaches_image(required_file):
    assert not _is_excluded(required_file), (
        f"{required_file} is excluded from the image build context but the "
        f"runtime needs it."
    )


def test_dockerignore_secret_list_covers_gitignore_secret_block():
    """The two lists are maintained by hand in two files; this pins that no
    secret filename in .gitignore's 'Local secrets' block is missing from
    .dockerignore (the failure mode that let lean.live.json slip through)."""
    gitignore = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
    block = gitignore.split("# Local secrets and broker/API credentials")[1]
    block = block.split("# OS/editor noise")[0]

    for raw in block.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("!"):
            continue
        # Wildcards/globs are covered by the parametrized checks above.
        if "*" in line:
            continue
        assert _is_excluded(line), (
            f"{line} is git-ignored as a secret but would still be copied into "
            f"the Docker image - add it to .dockerignore."
        )
