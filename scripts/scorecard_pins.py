"""The Scorecard's Pinned-Dependencies rule, offline (V6.6.7, #361): every install in the repo is pinned by hash.

OpenSSF Scorecard scans every workflow `run:` step, every `*Dockerfile*` and every shell script, and scores the share of
pinned commands per ecosystem. This mirrors its rules (checks/raw/shell_download_validate.go and the Dockerfile and
workflow parsers) so a regression fails in CI's fast guards instead of a week later on the Scorecard:

- pip (`pip`, `pip3`, `python -m pip`, any path ending in them) `install` is pinned with `--require-hashes`, with only
  `*.whl` arguments, or as `--no-deps -e <local path or git+...@<40 hex>>`; anything else is not;
- npm: `npm ci` is pinned, `npm install|i|update|install-test` is not;
- `curl`/`wget` piped into a shell is not;
- `uses:` must name a 40-hex commit (or `./local`, or `docker://...@sha256:`);
- `FROM` must carry `@sha256:<64 hex>` (ARG defaults resolved; `scratch` and earlier stage names are fine).

    python scripts/scorecard_pins.py      # exit 1 with one line per unpinned command
"""

from __future__ import annotations

import re
import shlex
import subprocess
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

import yaml

ROOT = Path(__file__).resolve().parents[1]
_FLAG = re.compile(r"^(--?\w+)+$")
_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_DIGEST = re.compile(r"@sha256:([0-9a-f]{64}|\$\{.*\})")
_GIT_EDITABLE = re.compile(r"^git(\+(https?|ssh|git))?://.*(\.git)?@[a-fA-F0-9]{40}(#egg=.*)?$")
_SEPARATORS = {"&&", "||", ";", "|", "&", "(", ")", "{", "}", "then", "do", "else", "!"}
_SHELLS = {"sh", "bash", "mksh", "zsh", "dash"}


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    kind: str
    text: str

    def __str__(self) -> str:
        return f"{self.path}:{self.line}: {self.kind}: {self.text}"


def join_continuations(text: str) -> list[tuple[int, str]]:
    """Logical lines: a trailing backslash joins the next physical line; the number is the first line's."""
    out: list[tuple[int, str]] = []
    buffer, start = "", 0
    for number, raw in enumerate(text.splitlines(), start=1):
        if not buffer:
            start = number
        stripped = raw.rstrip()
        if stripped.endswith("\\"):
            buffer += stripped[:-1] + " "
            continue
        out.append((start, buffer + raw))
        buffer = ""
    if buffer:
        out.append((start, buffer))
    return out


def _tokens(line: str) -> list[str]:
    code = line.split(" #", 1)[0] if not line.lstrip().startswith("#") else ""
    for operator in ("&&", "||", ";", "|", "(", ")"):
        code = code.replace(operator, f" {operator} ")
    try:
        return shlex.split(code, posix=True)
    except ValueError:
        return code.split()


def commands(line: str) -> list[list[str]]:
    """Simple commands on one logical line, split at shell operators; `sudo`, `env` and `VAR=x` prefixes dropped."""
    out: list[list[str]] = []
    current: list[str] = []
    for token in _tokens(line) + [";"]:
        if token in _SEPARATORS:
            if current:
                out.append(current)
            current = []
            continue
        if not current and (token in {"sudo", "env", "exec", "RUN"} or re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", token)):
            continue
        current.append(token)
    return out


def _base(word: str) -> str:
    return PurePosixPath(word.replace("\\", "/")).name


def pip_install_args(argv: Sequence[str]) -> list[str] | None:
    """The arguments after `install` when `argv` is a pip install, else None."""
    if not argv:
        return None
    head = _base(argv[0])
    if head in {"pip", "pip3"} and len(argv) > 1 and argv[1] == "install":
        return list(argv[2:])
    if re.fullmatch(r"python(3(\.\d+)?|2\.7)?(\.exe)?", head) and list(argv[1:4]) == ["-m", "pip", "install"]:
        return list(argv[4:])
    return None


def is_pinned_pip(args: Sequence[str]) -> bool:
    """Scorecard's isUnpinnedPipInstall, negated, over the arguments after `install`."""
    has_require_hashes = has_additional = has_wheel = has_no_deps = False
    editable_pinned: bool | None = None
    index = 0
    while index < len(args):
        arg = args[index]
        if arg == "--require-hashes":
            has_require_hashes = True
            break
        if arg == "--no-deps":
            has_no_deps = True
        elif arg in {"-e", "--editable"}:
            source = args[index + 1] if index + 1 < len(args) else ""
            editable_pinned = bool(source) and ("://" not in source or bool(_GIT_EDITABLE.match(source)))
            index += 2
            continue
        elif _FLAG.match(arg):
            pass
        elif arg.endswith(".whl"):
            has_wheel = True
        else:
            has_additional = True
        index += 1
    if editable_pinned is not None:
        return has_no_deps and editable_pinned and not has_additional
    if has_require_hashes:
        return True
    if has_additional:
        return False
    return has_wheel


def is_pinned_npm(argv: Sequence[str]) -> bool | None:
    """None when `argv` is no npm download; True for `npm ci`; False for install, i, update and install-test."""
    if len(argv) < 2 or _base(argv[0]) != "npm":
        return None
    verb = argv[1]
    if verb == "ci":
        return True
    if verb in {"install", "i", "install-test", "update"}:
        return False
    return None


def shell_findings(path: str, text: str) -> list[Finding]:
    found: list[Finding] = []
    for number, line in join_continuations(text):
        parts = commands(line)
        for argv in parts:
            pip_args = pip_install_args(argv)
            if pip_args is not None and not is_pinned_pip(pip_args):
                found.append(Finding(path, number, "pip", " ".join(argv)))
            if is_pinned_npm(argv) is False:
                found.append(Finding(path, number, "npm", " ".join(argv)))
        found += _pipe_to_shell(path, number, line)
    return found


def _pipe_to_shell(path: str, number: int, line: str) -> list[Finding]:
    segments = [segment.split() for segment in re.split(r"(?<!\|)\|(?!\|)", line)]
    for left, right in zip(segments, segments[1:]):
        fetches = bool(left) and _base(left[0]) in {"curl", "wget"}
        runs = [word for word in right if word != "sudo"][:1]
        if fetches and runs and _base(runs[0]) in _SHELLS:
            return [Finding(path, number, "download-pipe-shell", line.strip())]
    return []


def workflow_findings(path: str, text: str) -> list[Finding]:
    found: list[Finding] = []
    lines = text.splitlines()
    for number, line in enumerate(lines, start=1):
        match = re.match(r"^\s*-?\s*uses:\s*['\"]?([^'\"\s#]+)", line)
        if not match:
            continue
        ref = match.group(1)
        if ref.startswith("./") or (ref.startswith("docker://") and _DIGEST.search(ref)):
            continue
        if "@" not in ref or not _SHA40.match(ref.rsplit("@", 1)[1]):
            found.append(Finding(path, number, "action", ref))
    document = yaml.safe_load(text) or {}
    for job in (document.get("jobs") or {}).values():
        for step in (job or {}).get("steps") or []:
            run = (step or {}).get("run")
            if not isinstance(run, str):
                continue
            offset = _line_of(lines, run)
            found += [Finding(path, offset + item.line - 1, item.kind, item.text) for item in shell_findings(path, run)]
    return found


def _line_of(lines: list[str], run: str) -> int:
    first = next((line.strip() for line in run.splitlines() if line.strip()), "")
    return next((number for number, line in enumerate(lines, start=1) if first and first in line), 1)


def dockerfile_findings(path: str, text: str) -> list[Finding]:
    found: list[Finding] = []
    args: dict[str, str] = {}
    stages: set[str] = set()
    for number, line in join_continuations(text):
        words = line.split()
        if not words or words[0].startswith("#"):
            continue
        keyword = words[0].upper()
        if keyword == "ARG" and len(words) > 1 and "=" in words[1]:
            name, value = words[1].split("=", 1)
            args[name] = value.strip("\"'")
        elif keyword == "FROM":
            rest = [word for word in words[1:] if not word.startswith("--")]
            image = re.sub(r"\$\{?(\w+)\}?", lambda m: args.get(m.group(1), m.group(0)), rest[0]) if rest else ""
            if len(rest) >= 3 and rest[1].upper() == "AS":
                stages.add(rest[2].lower())
            if image.lower() != "scratch" and image.lower() not in stages and not _DIGEST.search(image):
                found.append(Finding(path, number, "image", image))
        elif keyword == "RUN":
            found += [Finding(path, number, item.kind, item.text) for item in shell_findings(path, " ".join(words[1:]))]
    return found


def is_shell_script(path: str, first_line: str) -> bool:
    if PurePosixPath(path).suffix in {".sh", ".bash", ".mksh"}:
        return True
    match = re.match(r"^#!\s*(\S+)(?:\s+(\S+))?", first_line)
    if not match:
        return False
    interpreter = _base(match.group(1))
    if interpreter == "env" and match.group(2):
        interpreter = _base(match.group(2))
    return interpreter in {"sh", "bash", "mksh"}


def is_dockerfile(path: str) -> bool:
    name = PurePosixPath(path).name.lower()
    return "dockerfile" in name and PurePosixPath(path).suffix not in {".py", ".sh", ".md", ".yml", ".yaml", ".json", ".txt"}


def tracked(root: Path = ROOT) -> list[str]:
    """Every file git would commit: tracked, plus new files not ignored (so a pin is checked before its first commit)."""
    output = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard"], cwd=root, capture_output=True, text=True, check=True, timeout=60).stdout
    return [line for line in output.splitlines() if line]


def scan(root: Path = ROOT, paths: Iterable[str] | None = None) -> list[Finding]:
    found: list[Finding] = []
    for path in paths if paths is not None else tracked(root):
        full = root / path
        if not full.is_file() or full.stat().st_size > 2_000_000:
            continue
        posix = PurePosixPath(path)
        if posix.parts[:2] == (".github", "workflows") and posix.suffix in {".yml", ".yaml"}:
            found += workflow_findings(path, full.read_text(encoding="utf-8"))
        elif is_dockerfile(path):
            found += dockerfile_findings(path, full.read_text(encoding="utf-8"))
        elif posix.suffix in {"", ".sh", ".bash", ".mksh"}:
            text = full.read_text(encoding="utf-8", errors="replace")
            if is_shell_script(path, text.split("\n", 1)[0]):
                found += shell_findings(path, text)
    return found


def main(argv: Sequence[str] | None = None) -> int:
    findings = scan()
    for finding in findings:
        print(finding)
    print(f"{len(findings)} unpinned dependency command(s)", file=sys.stderr if findings else sys.stdout)
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
