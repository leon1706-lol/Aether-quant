"""Installs the repository's pre-commit hook into this clone's `.git/hooks` (V6.6.4).

The hook runs `aq secrets-check` and the library gate (`.githooks/pre-commit`). It is installed as a small wrapper in `.git/hooks/pre-commit`, not through `core.hooksPath`, because pointing
`core.hooksPath` at `.githooks` would switch off the Git LFS hooks that already live in `.git/hooks`. An existing `pre-commit` that is not this wrapper is left alone and reported.

    python scripts/install_hooks.py            # install
    python scripts/install_hooks.py --check    # exit 1 if it is not installed
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MARKER = "# aether-quant pre-commit wrapper"
WRAPPER = f"""#!/bin/sh
{MARKER}: runs .githooks/pre-commit (secrets check and the library gate). Reinstall with `python scripts/install_hooks.py`.
repo_root=$(git rev-parse --show-toplevel)
[ -f "$repo_root/.githooks/pre-commit" ] || exit 0  # a worktree of a data-only branch (forward-ledger) has no script to run
exec sh "$repo_root/.githooks/pre-commit" "$@"
"""


def hooks_directory(root: Path = ROOT) -> Path:
    result = subprocess.run(["git", "rev-parse", "--git-path", "hooks"], cwd=root, capture_output=True, text=True, check=True)
    path = Path(result.stdout.strip())
    return path if path.is_absolute() else root / path


def installed(root: Path = ROOT) -> bool:
    target = hooks_directory(root) / "pre-commit"
    return target.exists() and MARKER in target.read_text(encoding="utf-8", errors="replace")


def install(root: Path = ROOT) -> str:
    target = hooks_directory(root) / "pre-commit"
    if target.exists() and MARKER not in target.read_text(encoding="utf-8", errors="replace"):
        return f"{target} exists and is not this wrapper: left alone"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(WRAPPER, encoding="utf-8", newline="\n")
    try:
        target.chmod(0o755)
    except OSError:
        pass
    return f"installed {target}"


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if "--check" in args:
        print("installed" if installed() else "not installed")
        return 0 if installed() else 1
    message = install()
    print(message)
    return 0 if installed() else 1


if __name__ == "__main__":
    raise SystemExit(main())
