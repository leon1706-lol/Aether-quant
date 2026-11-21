"""Developer and maintainer commands of `aq`: the commit gate, the environment, CI, dependencies, coverage, Codespaces,
the vault, Problems, lint, the CLI's own docs and completion, and the project's at-a-glance status.

Every command is a `cmd_*(args) -> int`, registered by `register(subparsers)` from `aq_cli.build_parser()`. Every
subprocess goes through `RUN` (tests replace it), so nothing here calls git, gh, npm or docker under test. Commands
that need a source checkout (scripts/, .git, .githooks) say so and exit 1 on a wheel install.

Exit codes: 0 ok, 1 failure, 2 usage, 3 a gate failed or something is still running, 130 interrupted.
"""

from __future__ import annotations

import argparse
import datetime as _datetime
import difflib
import fnmatch
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _package_version
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parent
RUN: Callable[..., subprocess.CompletedProcess] = subprocess.run
COVERAGE_MARKER = "aq-skip-coverage"
COVERAGE_STATES = ("persistent", "once")
PACKAGE_NAME = "aether-quant"
EXIT_OK, EXIT_FAIL, EXIT_USAGE, EXIT_GATE, EXIT_INTERRUPTED = 0, 1, 2, 3, 130


# ---------------------------------------------------------------------------
# shared helpers
# ---------------------------------------------------------------------------


def run_capture(command: Sequence[str], *, cwd: Path | None = None, env: Mapping[str, str] | None = None, timeout: float | None = 120) -> tuple[int, str]:
    """(exit code, stdout+stderr) of `command`; a missing program or a timeout is exit 127 / 124 with the reason as text."""
    try:
        result = RUN(list(command), cwd=str(cwd or ROOT_DIR), env=dict(env) if env is not None else None, capture_output=True, text=True, check=False, timeout=timeout)
    except FileNotFoundError:
        return 127, f"{command[0]}: not found"
    except subprocess.TimeoutExpired:
        return 124, f"{command[0]}: timed out"
    return result.returncode, (result.stdout or "") + (result.stderr or "")


def run_live(command: Sequence[str], *, cwd: Path | None = None, env: Mapping[str, str] | None = None) -> int:
    """Run `command` with the terminal attached; a missing program is exit 127 with one line on stderr."""
    try:
        return RUN(list(command), cwd=str(cwd or ROOT_DIR), env=dict(env) if env is not None else None, check=False).returncode
    except FileNotFoundError:
        print(f"aq: {command[0]} not found on PATH", file=sys.stderr)
        return 127


def emit(data: Any, as_json: bool, render: Callable[[Any], str] | None = None) -> None:
    """Print `data` as JSON (finite-safe) or through `render`."""
    if as_json:
        from json_safety import sanitize_json_finite

        print(json.dumps(sanitize_json_finite(data), indent=2, sort_keys=True, default=str))
    else:
        print(render(data) if render else str(data))


def confirm(prompt: str, *, assume_yes: bool, isatty: Callable[[], bool] | None = None, ask: Callable[[str], str] = input) -> bool:
    """True when `--yes` was given or the user typed y on a terminal; never prompts without a terminal."""
    if assume_yes:
        return True
    if not (isatty or sys.stdin.isatty)():
        print(f"aq: {prompt} - pass --yes to confirm", file=sys.stderr)
        return False
    return ask(f"{prompt} [y/N] ").strip().lower() in {"y", "yes"}


def add_json_flag(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--json", action="store_true", help="Print JSON instead of text")


def add_dry_run_flag(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--dry-run", action="store_true", help="Print what would happen, change nothing")


def add_yes_flag(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--yes", action="store_true", help="Confirm without a prompt (needed without a terminal)")


def source_checkout(root: Path = ROOT_DIR) -> bool:
    """A git checkout of this project (scripts/ and .githooks/ exist), not a wheel install."""
    return (root / "scripts").is_dir() and (root / ".githooks").is_dir() and (root / "pyproject.toml").is_file()


def needs_checkout(root: Path = ROOT_DIR) -> int | None:
    if source_checkout(root):
        return None
    print("aq: this command needs a source checkout of Aether Quant (git clone https://github.com/leon1706-lol/Aether-quant)", file=sys.stderr)
    return EXIT_FAIL


def color(text: str, code: str) -> str:
    """ANSI colour unless NO_COLOR is set or stdout is not a terminal."""
    if os.environ.get("NO_COLOR") or not sys.stdout.isatty():
        return text
    return f"\x1b[{code}m{text}\x1b[0m"


def _epilog(*examples: str) -> str:
    return "Examples:\n" + "\n".join(f"  {example}" for example in examples)


def _parser(subparsers, name: str, help_text: str, *examples: str) -> argparse.ArgumentParser:
    return subparsers.add_parser(name, help=help_text.replace("%", "%%"), description=help_text, epilog=_epilog(*examples), formatter_class=argparse.RawDescriptionHelpFormatter)


def installed_version() -> str:
    try:
        return _package_version(PACKAGE_NAME)
    except PackageNotFoundError:
        return "unknown"


# ---------------------------------------------------------------------------
# hooks: the pre-commit gate and its coverage switch
# ---------------------------------------------------------------------------


def git_path(name: str, root: Path = ROOT_DIR) -> Path:
    """`git rev-parse --git-path NAME`, resolved against `root`."""
    code, out = run_capture(["git", "rev-parse", "--git-path", name], cwd=root)
    if code != 0 or not out.strip():
        return root / ".git" / name
    path = Path(out.strip().splitlines()[-1])
    return path if path.is_absolute() else root / path


def coverage_state(marker: Path) -> str:
    """'on', 'off' (persistent) or 'once' (the next commit only)."""
    if not marker.exists():
        return "on"
    content = marker.read_text(encoding="utf-8").strip()
    return "once" if content == "once" else "off"


def set_coverage(marker: Path, state: str) -> str:
    """Write or remove the marker the pre-commit hook reads; returns the new state."""
    if state == "on":
        marker.unlink(missing_ok=True)
        return "on"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("once" if state == "once" else "persistent", encoding="utf-8", newline="\n")
    return coverage_state(marker)


HOOK_GATES = ("secrets-check", "library gate", "formal inventory", "scorecard pins", "ruff (staged .py)", "coverage of changed modules")


def hooks_status(root: Path = ROOT_DIR) -> dict:
    sys.path.insert(0, str(root / "scripts"))
    try:
        import install_hooks
    finally:
        sys.path.pop(0)
    coverage_json = root / "coverage-report" / "coverage.json"
    return {
        "installed": install_hooks.installed(root),
        "gates": list(HOOK_GATES),
        "coverage": coverage_state(git_path(COVERAGE_MARKER, root)),
        "coverage_json_age_hours": round((time.time() - coverage_json.stat().st_mtime) / 3600, 1) if coverage_json.exists() else None,
    }


def _render_hooks_status(status: dict) -> str:
    age = status["coverage_json_age_hours"]
    return "\n".join([
        f"pre-commit wrapper: {'installed' if status['installed'] else 'NOT installed (aq hooks install)'}",
        f"gates: {', '.join(status['gates'])}",
        f"coverage gate: {status['coverage']}" + ("" if status["coverage"] == "on" else " (turn on: aq hooks coverage on)"),
        f"coverage-report/coverage.json: {'missing' if age is None else f'{age} h old'}",
    ])


def cmd_hooks(args: argparse.Namespace) -> int:
    if (missing := needs_checkout()) is not None:
        return missing
    if args.hooks_command == "install":
        if args.dry_run:
            print("would install .git/hooks/pre-commit (a wrapper that runs .githooks/pre-commit)")
            return EXIT_OK
        sys.path.insert(0, str(ROOT_DIR / "scripts"))
        try:
            import install_hooks
        finally:
            sys.path.pop(0)
        print(install_hooks.install(ROOT_DIR))
        return EXIT_OK if install_hooks.installed(ROOT_DIR) else EXIT_FAIL
    if args.hooks_command == "status":
        emit(hooks_status(), args.json, _render_hooks_status)
        return EXIT_OK
    marker = git_path(COVERAGE_MARKER)
    action = args.coverage_action
    if action == "status":
        emit({"coverage": coverage_state(marker)}, args.json, lambda data: f"coverage gate: {data['coverage']}")
        return EXIT_OK
    target = "on" if action == "on" else ("once" if args.once else "off")
    if args.dry_run:
        print(f"coverage gate: {coverage_state(marker)} -> {target} (dry run)")
        return EXIT_OK
    state = set_coverage(marker, target)
    print(f"coverage gate: {state}")
    if state != "on":
        print("warning: CI's python-tests still enforces 100% coverage; run `aq test --coverage` before pushing", file=sys.stderr)
    return EXIT_OK


def cmd_commit(args: argparse.Namespace) -> int:
    """`git commit` with the coverage gate skipped for this one commit when asked; the other gates still run."""
    command = ["git", "commit", "-m", args.message, *(["-a"] if args.all else []), *(args.git_args or [])]
    env = {**os.environ}
    if args.skip_coverage:
        env["AQ_SKIP_COVERAGE_HOOK"] = "1"
        print("coverage gate skipped for this commit; run `aq test --coverage` before pushing", file=sys.stderr)
    if args.dry_run:
        print(("AQ_SKIP_COVERAGE_HOOK=1 " if args.skip_coverage else "") + " ".join(command))
        return EXIT_OK
    return run_live(command, env=env)


def cmd_check(args: argparse.Namespace) -> int:
    """Run exactly the pre-commit hook, committing nothing."""
    if (missing := needs_checkout()) is not None:
        return missing
    env = {**os.environ, **({"AQ_SKIP_COVERAGE_HOOK": "1"} if args.no_coverage else {})}
    sh = shutil.which("sh") or shutil.which("bash")
    if sh is None:
        print("aq check: no sh found (Git for Windows ships one)", file=sys.stderr)
        return EXIT_FAIL
    return run_live([sh, str(ROOT_DIR / ".githooks" / "pre-commit")], env=env)


# ---------------------------------------------------------------------------
# doctor
# ---------------------------------------------------------------------------


def _check(name: str, status: str, detail: str, fix: str = "") -> dict:
    return {"name": name, "status": status, "detail": detail, "fix": fix}


def _total_ram_gb() -> float | None:
    try:
        import psutil

        return psutil.virtual_memory().total / 1e9
    except ImportError:
        pass
    if sys.platform == "win32":
        import ctypes

        class _Status(ctypes.Structure):
            _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong), ("total", ctypes.c_ulonglong), ("avail", ctypes.c_ulonglong),
                        ("total_page", ctypes.c_ulonglong), ("avail_page", ctypes.c_ulonglong), ("total_virtual", ctypes.c_ulonglong),
                        ("avail_virtual", ctypes.c_ulonglong), ("avail_extended", ctypes.c_ulonglong)]

        status = _Status()
        status.length = ctypes.sizeof(_Status)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
        return status.total / 1e9
    try:
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 1e9
    except (ValueError, OSError, AttributeError):
        return None


def _tcp_open(host: str, port: int, timeout: float = 1.0) -> bool:
    import socket

    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


DOCTOR_PROBES: dict[str, Callable[..., Any]] = {
    "which": shutil.which,
    "ram_gb": _total_ram_gb,
    "disk_free_gb": lambda root: shutil.disk_usage(root).free / 1e9,
    "tcp_open": _tcp_open,
    "run": run_capture,
}


def _editable_check(root: Path) -> dict:
    import importlib.util

    text = (root / "pyproject.toml").read_text(encoding="utf-8") if (root / "pyproject.toml").exists() else ""
    match = re.search(r"^py-modules = \[(.*?)\]", text, re.MULTILINE)
    modules = re.findall(r'"([^"]+)"', match.group(1)) if match else []
    missing = [name for name in modules if importlib.util.find_spec(name) is None]
    if missing:
        return _check("editable install", "fail", f"not importable: {', '.join(missing)}", "pip install -e .")
    spec = importlib.util.find_spec("aq_cli")
    origin = Path(spec.origin).resolve().parent if spec and spec.origin else None
    if origin is not None and origin != root.resolve():
        return _check("editable install", "warn", f"aq_cli loads from {origin}, not this checkout", "pip install -e .")
    return _check("editable install", "ok", f"{len(modules)} top-level modules import from this checkout")


def doctor_checks(root: Path = ROOT_DIR, probes: Mapping[str, Callable[..., Any]] = DOCTOR_PROBES) -> list[dict]:
    """Every environment check, each {name, status: ok|warn|fail|skip, detail, fix}."""
    which = probes["which"]
    checks: list[dict] = []
    version = sys.version_info
    if version < (3, 10):
        checks.append(_check("python", "fail", platform.python_version(), "install Python 3.10 or newer"))
    elif version < (3, 11):
        checks.append(_check("python", "warn", f"{platform.python_version()}: pipeline files and some tools need 3.11", "use Python 3.11+"))
    else:
        checks.append(_check("python", "ok", platform.python_version()))
    checkout = source_checkout(root)
    checks.append(_editable_check(root) if checkout else _check("editable install", "skip", "a wheel install"))
    checks.append(_check("aq on PATH", "ok" if which("aq") else "warn", which("aq") or "not found", "pip install -e . (or add the Scripts folder to PATH)"))
    if checkout:
        state = hooks_status(root)
        checks.append(_check("pre-commit hook", "ok" if state["installed"] else "warn", "installed" if state["installed"] else "not installed", "aq hooks install"))
        checks.append(_check("coverage gate", "ok" if state["coverage"] == "on" else "warn", state["coverage"], "aq hooks coverage on"))
    for tool, fix, level in (("git", "install git", "fail"), ("gh", "install the GitHub CLI and run gh auth login", "warn"), ("uv", "pip install uv", "warn"),
                             ("docker", "install Docker Desktop (Lean backtests, the dashboard image)", "warn"), ("node", "install Node.js (webui)", "warn")):
        found = which(tool)
        checks.append(_check(tool, "ok" if found else level, found or "not found", fix))
    if which("gh"):
        code, _ = probes["run"](["gh", "auth", "status"])
        checks.append(_check("gh auth", "ok" if code == 0 else "warn", "logged in" if code == 0 else "not logged in", "gh auth login"))
    if which("docker"):
        code, _ = probes["run"](["docker", "info", "--format", "{{.ServerVersion}}"], timeout=20)
        checks.append(_check("docker daemon", "ok" if code == 0 else "warn", "running" if code == 0 else "not running", "start Docker Desktop"))
    if checkout and (root / "formal").is_dir():
        checks.append(_check("elan (Lean 4)", "ok" if which("lake") else "skip", which("lake") or "not installed: only `aq prove` needs it"))
    for name, port in (("redis", 6379), ("postgres", 5432)):
        up = probes["tcp_open"]("127.0.0.1", port)
        checks.append(_check(name, "ok" if up else "warn", f"localhost:{port} {'open' if up else 'closed'}", "aq docker up (optional: everything degrades without it)"))
    ram = probes["ram_gb"]()
    if ram is None:
        checks.append(_check("RAM", "skip", "unknown"))
    elif ram < 8:
        checks.append(_check("RAM", "warn", f"{ram:.1f} GB", "train with --memory-profile low; never aq test --parallel"))
    else:
        checks.append(_check("RAM", "ok", f"{ram:.1f} GB"))
    free = probes["disk_free_gb"](root)
    checks.append(_check("disk", "ok" if free >= 10 else "warn", f"{free:.0f} GB free", "free space: aq clean ml / coverage / caches"))
    pins = root / "ml" / "artifact_pins.json"
    if pins.exists():
        from retraining.artifact_pins import artifact_problems

        problems = artifact_problems(root / "ml", pins)
        checks.append(_check("model pins", "ok" if not problems else "fail", "ml/ matches its sha256 pins" if not problems else "; ".join(problems[:3]), "restore ml/ from the vault or rerun the install"))
    else:
        checks.append(_check("model pins", "skip", "no ml/ (the project's models are private)"))
    config = root / "config.json"
    if config.exists():
        try:
            json.loads(config.read_text(encoding="utf-8"))
            checks.append(_check("config.json", "ok", "parses"))
        except ValueError as error:
            checks.append(_check("config.json", "fail", str(error), "fix the JSON"))
    return checks


_STATUS_MARK = {"ok": "ok  ", "warn": "WARN", "fail": "FAIL", "skip": "skip"}
_STATUS_COLOR = {"ok": "32", "warn": "33", "fail": "31", "skip": "90"}


def render_checks(checks: Sequence[dict]) -> str:
    lines = []
    for check in checks:
        mark = color(_STATUS_MARK[check["status"]], _STATUS_COLOR[check["status"]])
        fix = f"  -> {check['fix']}" if check["status"] in {"warn", "fail"} and check["fix"] else ""
        lines.append(f"[{mark}] {check['name']}: {check['detail']}{fix}")
    counts = {status: sum(1 for check in checks if check["status"] == status) for status in _STATUS_MARK}
    lines.append(f"{counts['ok']} ok, {counts['warn']} warnings, {counts['fail']} failures, {counts['skip']} skipped")
    return "\n".join(lines)


def cmd_doctor(args: argparse.Namespace) -> int:
    checks = doctor_checks()
    emit(checks, args.json, render_checks)
    return EXIT_FAIL if any(check["status"] == "fail" for check in checks) else EXIT_OK


# ---------------------------------------------------------------------------
# version, completion, help
# ---------------------------------------------------------------------------


def version_info(root: Path = ROOT_DIR) -> dict:
    info = {"aether_quant": installed_version(), "python": platform.python_version(), "platform": platform.platform(), "source_checkout": source_checkout(root)}
    if info["source_checkout"]:
        code, sha = run_capture(["git", "rev-parse", "--short", "HEAD"], cwd=root)
        _, dirty = run_capture(["git", "status", "--porcelain", "--untracked-files=no"], cwd=root)
        info["git"] = sha.strip() if code == 0 else None
        info["dirty"] = bool(dirty.strip()) if code == 0 else None
    return info


def _render_version(info: dict) -> str:
    text = f"aq {info['aether_quant']} (python {info['python']}, {info['platform']})"
    if info.get("git"):
        text += f"\nsource checkout at {info['git']}{' with uncommitted changes' if info.get('dirty') else ''}"
    elif not info["source_checkout"]:
        text += "\nwheel install"
    return text


def cmd_version(args: argparse.Namespace) -> int:
    emit(version_info(), args.json, _render_version)
    return EXIT_OK


def _subparsers_of(parser: argparse.ArgumentParser) -> dict[str, argparse.ArgumentParser]:
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return dict(action.choices)
    return {}


def walk_commands(parser: argparse.ArgumentParser, prefix: tuple[str, ...] = ()) -> list[tuple[tuple[str, ...], argparse.ArgumentParser]]:
    """Every (command path, parser) pair under `parser`, depth first; the root is the empty path."""
    found = [(prefix, parser)]
    for name, child in _subparsers_of(parser).items():
        found += walk_commands(child, (*prefix, name))
    return found


def _options(parser: argparse.ArgumentParser) -> list[str]:
    return sorted({option for action in parser._actions for option in action.option_strings if option.startswith("--")})


def completion_script(parser: argparse.ArgumentParser, shell: str) -> str:
    """A static completion script for `shell` built from the parser tree: subcommand names, then each command's flags."""
    table = {" ".join(path): (sorted(_subparsers_of(sub)), _options(sub)) for path, sub in walk_commands(parser)}
    if shell == "powershell":
        entries = "\n".join(f"    '{key}' = @({', '.join(repr(word) for word in [*subs, *opts])})" for key, (subs, opts) in sorted(table.items()))
        return f"""# aq completion for PowerShell: aq completion powershell >> $PROFILE
$aqWords = @{{
{entries}
}}
Register-ArgumentCompleter -Native -CommandName aq -ScriptBlock {{
    param($wordToComplete, $commandAst, $cursorPosition)
    $parts = @($commandAst.CommandElements | Select-Object -Skip 1 | ForEach-Object {{ $_.ToString() }} | Where-Object {{ $_ -notlike '-*' -and $_ -ne $wordToComplete }})
    $key = ($parts -join ' ')
    while ($key -ne '' -and -not $aqWords.ContainsKey($key)) {{ $key = ($key -replace ' ?[^ ]+$', '') }}
    $aqWords[$key] | Where-Object {{ $_ -like "$wordToComplete*" }} | ForEach-Object {{ [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterValue', $_) }}
}}
"""
    cases = "\n".join(f'        "{key}") words="{" ".join([*subs, *opts])}" ;;' for key, (subs, opts) in sorted(table.items()))
    body = f"""_aq_complete() {{
    local cur key words i
    cur="${{COMP_WORDS[COMP_CWORD]}}"
    key=""
    for ((i=1; i<COMP_CWORD; i++)); do
        case "${{COMP_WORDS[i]}}" in -*) ;; *) key="${{key:+$key }}${{COMP_WORDS[i]}}" ;; esac
    done
    while :; do
        case "$key" in
{cases}
        *) key="${{key% *}}"; [ "$key" = "${{key% *}}" ] && [ -z "${{key##* *}}" ] && key=""; continue ;;
        esac
        break
    done
    COMPREPLY=($(compgen -W "$words" -- "$cur"))
}}
complete -F _aq_complete aq
"""
    if shell == "zsh":
        return "# aq completion for zsh: aq completion zsh >> ~/.zshrc\nautoload -U +X bashcompinit && bashcompinit\n" + body
    return "# aq completion for bash: aq completion bash >> ~/.bashrc\n" + body


def cmd_completion(args: argparse.Namespace) -> int:
    from aq_cli import build_parser

    print(completion_script(build_parser(), args.shell))
    return EXIT_OK


def cmd_help(args: argparse.Namespace) -> int:
    from aq_cli import build_parser

    parser = build_parser()
    target = parser
    for word in args.topic or []:
        children = _subparsers_of(target)
        if word not in children:
            close = difflib.get_close_matches(word, list(children), n=3)
            print(f"aq help: no command {word!r}" + (f"; did you mean: {', '.join(close)}?" if close else ""), file=sys.stderr)
            return EXIT_USAGE
        target = children[word]
    target.print_help()
    return EXIT_OK


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------


def _todo_objective(root: Path) -> str | None:
    todo = root / "todo.md"
    if not todo.exists():
        return None
    match = re.search(r"^# Current objective:\s*(.+)$", todo.read_text(encoding="utf-8"), re.MULTILINE)
    return match.group(1).strip() if match else None


def status_report(root: Path = ROOT_DIR, *, online: bool = True) -> dict:
    """Branch, sync, dirty files, last commit, hook and coverage state, CI of HEAD, Dependabot PRs, Codespaces, the objective."""
    report: dict[str, Any] = {"objective": _todo_objective(root)}
    code, branch = run_capture(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=root)
    if code != 0:
        report["git"] = None
        return report
    _, porcelain = run_capture(["git", "status", "--porcelain"], cwd=root)
    _, last = run_capture(["git", "log", "-1", "--format=%h %s (%cr)"], cwd=root)
    sync_code, sync = run_capture(["git", "rev-list", "--left-right", "--count", "@{upstream}...HEAD"], cwd=root)
    behind, ahead = (sync.split() + ["?", "?"])[:2] if sync_code == 0 else ("?", "?")
    report["git"] = {"branch": branch.strip(), "dirty": len([line for line in porcelain.splitlines() if line.strip()]), "last_commit": last.strip(), "ahead": ahead, "behind": behind}
    if source_checkout(root):
        hooks = hooks_status(root)
        report["hooks"] = {"installed": hooks["installed"], "coverage": hooks["coverage"], "coverage_json_age_hours": hooks["coverage_json_age_hours"]}
    if online and shutil.which("gh"):
        _, sha = run_capture(["git", "rev-parse", "HEAD"], cwd=root)
        runs = ci_runs(sha.strip())
        report["ci"] = summarize_runs(runs) if runs is not None else "unknown"
        report["dependabot_prs"] = len(dependabot_prs() or [])
        spaces = codespaces()
        report["codespaces_running"] = [space["name"] for space in spaces or [] if space.get("state") == "Available"]
    return report


def _render_status(report: dict) -> str:
    lines = []
    if report.get("objective"):
        lines.append(f"objective: {report['objective']}")
    git = report.get("git")
    if git is None:
        lines.append("git: not a git checkout")
        return "\n".join(lines)
    lines.append(f"branch {git['branch']} (ahead {git['ahead']}, behind {git['behind']}), {git['dirty']} changed file(s); last: {git['last_commit']}")
    if "hooks" in report:
        hooks = report["hooks"]
        age = hooks["coverage_json_age_hours"]
        lines.append(f"hook {'installed' if hooks['installed'] else 'NOT installed'}, coverage gate {hooks['coverage']}, coverage.json {'missing' if age is None else f'{age} h old'}")
    if "ci" in report:
        ci = report["ci"]
        lines.append("CI of HEAD: unknown" if ci == "unknown" else f"CI of HEAD: {ci['verdict']} ({', '.join(ci['failed']) or 'no failures'}{', running: ' + ', '.join(ci['running']) if ci['running'] else ''})")
        lines.append(f"open Dependabot PRs: {report['dependabot_prs']}")
        running = report["codespaces_running"]
        lines.append(color(f"Codespaces RUNNING (billing): {', '.join(running)}", "31") if running else "Codespaces: none running")
    return "\n".join(lines)


def cmd_status(args: argparse.Namespace) -> int:
    if args.git:
        return run_live(["git", "status"])
    emit(status_report(online=not args.offline), args.json, _render_status)
    return EXIT_OK


# ---------------------------------------------------------------------------
# CI (gh)
# ---------------------------------------------------------------------------


def _gh_json(command: Sequence[str]) -> Any:
    code, out = run_capture(["gh", *command], timeout=60)
    if code != 0:
        return None
    try:
        return json.loads(out)
    except ValueError:
        return None


def ci_runs(sha: str) -> list[dict] | None:
    """Every workflow run of commit `sha`, each with its jobs."""
    runs = _gh_json(["run", "list", "--commit", sha, "--limit", "50", "--json", "databaseId,workflowName,status,conclusion,event"])
    if runs is None:
        return None
    for run in runs:
        run["jobs"] = (_gh_json(["run", "view", str(run["databaseId"]), "--json", "jobs"]) or {}).get("jobs", [])
    return runs


def summarize_runs(runs: Sequence[dict]) -> dict:
    """{verdict: green|red|running|none, failed: [workflow / job], running: [workflow]}."""
    failed, running = [], []
    for run in runs:
        if run.get("status") != "completed":
            running.append(run.get("workflowName", "?"))
        bad_jobs = [job.get("name", "?") for job in run.get("jobs", []) if job.get("conclusion") in {"failure", "timed_out", "cancelled"}]
        if run.get("conclusion") in {"failure", "timed_out", "startup_failure"} or bad_jobs:
            failed += [f"{run.get('workflowName', '?')} / {job}" for job in bad_jobs] or [run.get("workflowName", "?")]
    verdict = "none" if not runs else "red" if failed else "running" if running else "green"
    return {"verdict": verdict, "failed": failed, "running": running, "runs": len(runs)}


LOG_PATTERN = re.compile(r"FAILED|Error|error:|AssertionError|Missing|fail_under|fail-under|requires !2|Traceback|ERESOLVE|##\[error\]")
_LOG_STAMP = re.compile(r"^\S+Z\s")


def filter_log(text: str, *, before: int = 3, cap: int = 80) -> list[str]:
    """The lines of a job log that explain a failure, each with up to `before` lines of context, at most `cap` lines."""
    lines = [_LOG_STAMP.sub("", line) for line in text.splitlines()]
    keep: list[int] = []
    for index, line in enumerate(lines):
        if LOG_PATTERN.search(line):
            keep.extend(range(max(0, index - before), index + 1))
    out, seen = [], set()
    for index in keep:
        if index not in seen:
            seen.add(index)
            out.append(lines[index])
    return out[-cap:]


def _repo_slug() -> str | None:
    data = _gh_json(["repo", "view", "--json", "nameWithOwner"])
    return data.get("nameWithOwner") if isinstance(data, dict) else None


def cmd_ci(args: argparse.Namespace) -> int:
    if args.ci_command == "local":
        return cmd_ci_local(args)
    if not shutil.which("gh"):
        print("aq ci: needs the GitHub CLI (gh) logged in: https://cli.github.com", file=sys.stderr)
        return EXIT_FAIL
    if args.ci_command == "logs":
        slug = _repo_slug()
        view = _gh_json(["run", "view", args.run_id, "--json", "jobs"])
        if slug is None or view is None:
            print(f"aq ci logs: run {args.run_id} not found", file=sys.stderr)
            return EXIT_FAIL
        jobs = [job for job in view.get("jobs", []) if (args.job and args.job in job.get("name", "")) or (not args.job and job.get("conclusion") == "failure")]
        lines = {}
        for job in jobs:
            _, log = run_capture(["gh", "api", f"repos/{slug}/actions/jobs/{job['databaseId']}/logs"], timeout=120)
            lines[job.get("name")] = filter_log(log, cap=args.lines)
        none = "no failed job" + (f" matching {args.job!r}" if args.job else "")
        emit(lines, getattr(args, "json", False),
             lambda data: "\n".join(f"=== {name}\n" + ("\n".join(rows) or "(no failure lines found)") for name, rows in data.items()) or none)
        return EXIT_OK
    ref = args.sha
    if args.branch:
        code, out = run_capture(["git", "rev-parse", f"origin/{args.branch}"])
        ref = out.strip() if code == 0 else args.branch
    code, sha = run_capture(["git", "rev-parse", ref])
    sha = sha.strip() if code == 0 else ref
    while True:
        runs = ci_runs(sha)
        if runs is None:
            print("aq ci status: gh could not list runs (gh auth status?)", file=sys.stderr)
            return EXIT_FAIL
        summary = summarize_runs(runs)
        if not args.watch or summary["verdict"] != "running":
            break
        print(f"{sha[:8]}: {len(summary['running'])} workflow(s) running ({', '.join(summary['running'])}); next check in {args.interval}s", flush=True)
        time.sleep(args.interval)
    summary["sha"] = sha

    def render(data: dict) -> str:
        head = {"green": color("green", "32"), "red": color("red", "31"), "running": color("running", "33"), "none": "no runs"}[data["verdict"]]
        lines = [f"{data['sha'][:8]}: {head} ({data['runs']} workflow run(s))"]
        lines += [f"  failed: {item}" for item in data["failed"]]
        lines += [f"  running: {item}" for item in data["running"]]
        if data["failed"]:
            lines.append("  details: aq ci logs <run-id>  (gh run list --commit " + data["sha"][:8] + ")")
        return "\n".join(lines)

    emit(summary, args.json, render)
    return {"green": EXIT_OK, "none": EXIT_OK, "red": EXIT_FAIL, "running": EXIT_GATE}[summary["verdict"]]


def ci_job_steps(workflow: Mapping[str, Any], job: str, matrix: Mapping[str, str] | None = None) -> list[dict]:
    """The steps of `job`: {name, run|uses, env}. `${{ matrix.KEY }}` is filled from `matrix` (default: each key's first value)."""
    spec = workflow.get("jobs", {}).get(job)
    if spec is None:
        raise KeyError(job)
    values = {key: (value[0] if isinstance(value, list) and value else value) for key, value in (spec.get("strategy", {}).get("matrix") or {}).items() if key not in {"include", "exclude"}}
    values.update(matrix or {})
    job_env = {key: str(value) for key, value in (spec.get("env") or {}).items()}

    def fill(text: str) -> str:
        return re.sub(r"\$\{\{\s*matrix\.([\w-]+)\s*\}\}", lambda match: str(values.get(match.group(1), match.group(0))), text)

    steps = []
    for index, step in enumerate(spec.get("steps", [])):
        entry = {"name": step.get("name") or step.get("uses") or f"step {index + 1}", "env": {**job_env, **{key: fill(str(value)) for key, value in (step.get("env") or {}).items()}}}
        if "run" in step:
            entry["run"] = fill(step["run"])
        else:
            entry["uses"] = step.get("uses", "")
        steps.append(entry)
    return steps


def ci_job_needs(workflow: Mapping[str, Any]) -> dict[str, list[str]]:
    """{job: what it needs that a PC may lack: docker, services, matrix}."""
    out = {}
    for name, spec in workflow.get("jobs", {}).items():
        needs = []
        text = json.dumps(spec)
        if "docker" in text.lower():
            needs.append("docker")
        if spec.get("services"):
            needs.append("services")
        if spec.get("strategy", {}).get("matrix"):
            needs.append("matrix")
        out[name] = needs
    return out


def cmd_ci_local(args: argparse.Namespace) -> int:
    if (missing := needs_checkout()) is not None:
        return missing
    import yaml

    workflow = yaml.safe_load((ROOT_DIR / ".github" / "workflows" / args.workflow).read_text(encoding="utf-8"))
    if args.list or not args.job:
        for name, needs in ci_job_needs(workflow).items():
            print(f"{name}" + (f"  (needs: {', '.join(needs)})" if needs else ""))
        return EXIT_OK
    matrix = dict(item.split("=", 1) for item in args.matrix or [])
    try:
        steps = ci_job_steps(workflow, args.job, matrix)
    except KeyError:
        close = difflib.get_close_matches(args.job, list(workflow.get("jobs", {})), n=3)
        print(f"aq ci local: no job {args.job!r} in {args.workflow}" + (f"; did you mean: {', '.join(close)}?" if close else ""), file=sys.stderr)
        return EXIT_USAGE
    bash = shutil.which("bash")
    for step in steps:
        if "uses" in step:
            print(f"-- skipped: {step['name']} ({step['uses']})")
            continue
        print(f"-- {step['name']}", flush=True)
        if args.dry_run:
            print(step["run"])
            continue
        if bash is None:
            print("aq ci local: bash not found (Git for Windows ships one)", file=sys.stderr)
            return EXIT_FAIL
        code = run_live([bash, "-e", "-c", step["run"]], env={**os.environ, **step["env"]})
        if code != 0:
            print(f"aq ci local: step {step['name']!r} failed (exit {code})", file=sys.stderr)
            return code
    return EXIT_OK


# ---------------------------------------------------------------------------
# dependencies
# ---------------------------------------------------------------------------

_TITLE_RE = re.compile(r"^(?:Bump|Update) (?P<pkg>\S+)(?: requirement)? from (?P<old>\S+) to (?P<new>\S+)(?: in (?P<dir>\S+))?$")


def parse_dependabot_title(title: str) -> dict | None:
    """{package, old, new, directory, ecosystem, major} from a Dependabot PR title, or None for a grouped/other title."""
    match = _TITLE_RE.match(title.strip())
    if not match:
        return None
    directory = match.group("dir") or "/"
    ecosystem = "pip" if directory.startswith("/requirements") else "npm" if directory.startswith("/webui") else "github-actions"

    def major(value: str) -> str:
        return re.sub(r"^[^\d]*", "", value).split(".")[0]

    return {"package": match.group("pkg"), "old": match.group("old"), "new": match.group("new"), "directory": directory, "ecosystem": ecosystem,
            "major": major(match.group("old")) != major(match.group("new"))}


def split_diff(diff: str) -> list[tuple[str, str]]:
    """[(path, file diff text)] of a unified git diff."""
    parts = re.split(r"(?m)^(?=diff --git )", diff)
    out = []
    for part in parts:
        match = re.match(r"diff --git a/(\S+) b/(\S+)", part)
        if match:
            out.append((match.group(2), part))
    return out


def without_lock_files(diff: str) -> str:
    """The diff without its `requirements/lock/*.txt` files, which only scripts/lock_requirements.py may write."""
    return "".join(text for path, text in split_diff(diff) if not fnmatch.fnmatch(path, "requirements/lock/*.txt"))


def lock_via(lock_text: str, package: str) -> list[str]:
    """What pulls `package` into a uv lock file: the `# via` lines under its pin."""
    lines = lock_text.splitlines()
    name = package.lower().replace("_", "-")
    for index, line in enumerate(lines):
        if re.match(rf"^{re.escape(name)}==", line.strip().lower().replace("_", "-")):
            via = []
            for follow in lines[index + 1:]:
                stripped = follow.strip()
                if not stripped or (not follow.startswith(" ") and not stripped.startswith("#")):
                    break
                if stripped.startswith("# via"):
                    first = stripped[len("# via"):].strip()
                    if first:
                        via.append(first)
                elif stripped.startswith("#"):
                    via.append(stripped.lstrip("#").strip())
            return via
    return []


def dependabot_prs() -> list[dict] | None:
    prs = _gh_json(["pr", "list", "--author", "app/dependabot", "--state", "open", "--json", "number,title,headRefName,statusCheckRollup"])
    if prs is None:
        return None
    for pr in prs:
        pr["parsed"] = parse_dependabot_title(pr.get("title", ""))
        checks = pr.get("statusCheckRollup") or []
        pr["checks"] = "failing" if any(check.get("conclusion") == "FAILURE" for check in checks) else "pending" if any(check.get("status") not in {None, "COMPLETED"} for check in checks) else "passing"
    return prs


def _render_prs(prs: Sequence[dict]) -> str:
    if not prs:
        return "no open Dependabot PRs"
    rows = []
    for pr in prs:
        parsed = pr["parsed"]
        what = f"{parsed['ecosystem']:<15} {parsed['package']} {parsed['old']} -> {parsed['new']}{' (major)' if parsed['major'] else ''}" if parsed else pr["title"]
        rows.append(f"#{pr['number']:<5} {pr['checks']:<8} {what}")
    return "\n".join(rows)


def cmd_deps(args: argparse.Namespace) -> int:
    if (missing := needs_checkout()) is not None:
        return missing
    command = args.deps_command
    if command == "lock":
        return run_live([sys.executable, "scripts/lock_requirements.py", *[part for profile in args.profile or [] for part in ("--profile", profile)],
                         *[part for package in args.upgrade_package or [] for part in ("--upgrade-package", package)]])
    if command == "pins":
        return run_live([sys.executable, "scripts/scorecard_pins.py"])
    if command == "audit":
        if not shutil.which("pip-audit"):
            print("aq deps audit: pip-audit not found: pip install --require-hashes -r requirements/lock/tools.txt", file=sys.stderr)
            return EXIT_FAIL
        worst = 0
        for profile in ("runtime", "ci"):
            worst = max(worst, run_live(["pip-audit", "--requirement", f"requirements/lock/{profile}.txt", "--require-hashes", "--disable-pip", "--desc"]))
        return worst
    if command == "why":
        rows = {}
        for lock in sorted((ROOT_DIR / "requirements" / "lock").glob("*.txt")):
            if args.profile and lock.stem not in args.profile:
                continue
            via = lock_via(lock.read_text(encoding="utf-8"), args.package)
            if via:
                rows[lock.stem] = via
        emit(rows, args.json, lambda data: "\n".join(f"{profile}: {', '.join(via)}" for profile, via in data.items()) or f"{args.package} is in no lock file")
        return EXIT_OK if rows else EXIT_FAIL
    if not shutil.which("gh"):
        print("aq deps: needs the GitHub CLI (gh) logged in", file=sys.stderr)
        return EXIT_FAIL
    if command == "prs":
        prs = dependabot_prs()
        if prs is None:
            print("aq deps prs: gh could not list pull requests", file=sys.stderr)
            return EXIT_FAIL
        emit(prs, args.json, _render_prs)
        return EXIT_OK
    worst = 0
    for number in args.numbers:
        worst = max(worst, apply_dependabot_pr(number, dry_run=args.dry_run))
    if worst == 0 and not args.dry_run:
        print("next: aq test --impacted, aq check, then aq commit -m '...'")
    return worst


def apply_dependabot_pr(number: str, *, dry_run: bool = False) -> int:
    """Apply one Dependabot PR to the working tree the way the checks accept it."""
    view = _gh_json(["pr", "view", str(number), "--json", "title"])
    parsed = parse_dependabot_title(view.get("title", "")) if isinstance(view, dict) else None
    if parsed is None:
        print(f"aq deps apply: #{number} is not a single-package Dependabot PR", file=sys.stderr)
        return EXIT_FAIL
    if parsed["ecosystem"] == "npm":
        command = ["npm", "install", f"{parsed['package']}@^{parsed['new']}"]
        print(f"#{number}: (cd webui) {' '.join(command)}")
        if dry_run:
            return EXIT_OK
        code = run_live(command, cwd=ROOT_DIR / "webui")
        _, tree = run_capture(["npm", "ls", "--all"], cwd=ROOT_DIR / "webui", timeout=300)
        if "invalid" in tree or "ERESOLVE" in tree:
            print("warning: npm reports invalid peers: bump the paired packages too (e.g. vitest with @vitest/coverage-v8, react with react-dom)", file=sys.stderr)
        return code
    code, diff = run_capture(["gh", "pr", "diff", str(number)], timeout=120)
    if code != 0:
        print(f"aq deps apply: could not read #{number}'s diff", file=sys.stderr)
        return EXIT_FAIL
    patch = without_lock_files(diff) if parsed["ecosystem"] == "pip" else diff
    print(f"#{number}: applying {len(split_diff(patch))} file(s) of {parsed['package']} {parsed['old']} -> {parsed['new']}")
    if dry_run:
        return EXIT_OK
    if patch.strip():
        result = RUN(["git", "apply", "-"], cwd=str(ROOT_DIR), input=patch, text=True, capture_output=True, check=False)
        if result.returncode != 0:
            print(f"aq deps apply: git apply failed: {result.stderr.strip()}", file=sys.stderr)
            return EXIT_FAIL
    if parsed["ecosystem"] == "pip":
        return run_live([sys.executable, "scripts/lock_requirements.py", "--upgrade-package", parsed["package"]])
    if parsed["package"].startswith("github/codeql-action/"):
        print("warning: bump every github/codeql-action/* use to the same SHA (init, analyze, upload-sarif)", file=sys.stderr)
    return EXIT_OK


# ---------------------------------------------------------------------------
# coverage
# ---------------------------------------------------------------------------


def coverage_summary(data: Mapping[str, Any], *, json_mtime: float | None = None, root: Path | None = None) -> dict:
    """Total percent, files below 100% and whether a tracked .py changed after the report."""
    root = root or ROOT_DIR
    files = data.get("files") or {}
    below = {name.replace("\\", "/"): report.get("summary", {}).get("percent_covered") for name, report in files.items() if report.get("missing_lines")}
    stale = []
    if json_mtime is not None:
        stale = sorted(name.replace("\\", "/") for name in files if (root / name).exists() and (root / name).stat().st_mtime > json_mtime)
    return {"percent": (data.get("totals") or {}).get("percent_covered"), "files": len(files), "below_100": below, "changed_since": stale}


def cmd_coverage(args: argparse.Namespace) -> int:
    report_path = ROOT_DIR / "coverage-report" / "coverage.json"
    if args.coverage_command == "misses":
        if (missing := needs_checkout()) is not None:
            return missing
        command = [sys.executable, "scripts/coverage_misses.py", *[part for pattern in args.include or [] for part in ("--include", pattern)]]
        command += ["--by-function"] if args.by_function else []
        command += ["--context", str(args.context)] if args.context is not None else []
        return run_live(command)
    if args.coverage_command == "clean":
        return clean_paths(coverage_paths(ROOT_DIR), apply=args.apply, assume_yes=args.yes, as_json=args.json, root=ROOT_DIR)
    if not report_path.exists():
        print("no coverage-report/coverage.json yet: aq test --coverage", file=sys.stderr)
        return EXIT_FAIL
    summary = coverage_summary(json.loads(report_path.read_text(encoding="utf-8")), json_mtime=report_path.stat().st_mtime)
    summary["age_hours"] = round((time.time() - report_path.stat().st_mtime) / 3600, 1)

    def render(data: dict) -> str:
        lines = [f"total {data['percent']:.2f}% over {data['files']} files, {data['age_hours']} h old"]
        lines += [f"  {name}: {percent:.1f}%" for name, percent in sorted(data["below_100"].items())]
        if data["changed_since"]:
            lines.append(f"  {len(data['changed_since'])} file(s) changed since: rerun (aq test --coverage --changed)")
        return "\n".join(lines)

    emit(summary, args.json, render)
    return EXIT_OK if not summary["below_100"] else EXIT_GATE


# ---------------------------------------------------------------------------
# cleaning (coverage, caches, build)
# ---------------------------------------------------------------------------

_NEVER_CLEAN = ("backtests", "ml", "data", ".git")


def coverage_paths(root: Path) -> list[Path]:
    return [path for path in [root / "coverage-report", *root.glob(".coverage*")] if path.exists()]


def cache_paths(root: Path) -> list[Path]:
    found = []
    for name in (".pytest_cache", ".ruff_cache", ".hypothesis", ".mypy_cache"):
        if (root / name).exists():
            found.append(root / name)
    for folder in ("aether_quant", "aq_devtools", "lab", "evaluation", "features", "portfolio", "risk", "execution", "retraining", "tests", "scripts", "inference",
                   "data_pipeline", "audit", "monitoring", "notifications", "performance", "regime", "topology", "liquidity", "moe", "experts", "experience", "analyzer"):
        found += [path for path in (root / folder).rglob("__pycache__") if path.is_dir()] if (root / folder).is_dir() else []
    if (root / "__pycache__").is_dir():
        found.append(root / "__pycache__")
    return found


def build_paths(root: Path) -> list[Path]:
    return [path for path in (root / "build", root / "dist") if path.exists()]


def _size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def clean_paths(paths: Sequence[Path], *, apply: bool, assume_yes: bool, as_json: bool, root: Path | None = None) -> int:
    root = root or ROOT_DIR
    safe = [path for path in paths if path.resolve().relative_to(root.resolve()).parts[:1] not in [(name,) for name in _NEVER_CLEAN]]
    rows = [{"path": str(path.relative_to(root)), "bytes": _size(path)} for path in safe]
    emit({"apply": apply, "items": rows, "bytes": sum(row["bytes"] for row in rows)}, as_json,
         lambda data: "\n".join([*(f"{row['path']} ({row['bytes'] / 1e6:.1f} MB)" for row in data["items"]),
                                 f"{'deleting' if apply else 'would delete (dry run; --apply deletes)'} {len(data['items'])} item(s), {data['bytes'] / 1e6:.1f} MB"]))
    if not apply or not safe:
        return EXIT_OK
    if not confirm(f"delete {len(safe)} item(s)?", assume_yes=assume_yes):
        return EXIT_USAGE
    for path in safe:
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
        else:
            path.unlink(missing_ok=True)
    return EXIT_OK


# ---------------------------------------------------------------------------
# Codespaces
# ---------------------------------------------------------------------------


def codespaces() -> list[dict] | None:
    return _gh_json(["codespace", "list", "--json", "name,displayName,state,lastUsedAt,repository"])


def cmd_codespace(args: argparse.Namespace) -> int:
    if not shutil.which("gh"):
        print("aq codespace: needs the GitHub CLI (gh) logged in", file=sys.stderr)
        return EXIT_FAIL
    spaces = codespaces()
    if spaces is None:
        print("aq codespace: gh could not list Codespaces (gh auth refresh -s codespace?)", file=sys.stderr)
        return EXIT_FAIL
    if args.codespace_command == "list":
        def render(data: list) -> str:
            if not data:
                return "no Codespaces"
            return "\n".join((color(f"{space['name']}  {space['state']} (BILLING)", "31") if space.get("state") == "Available" else f"{space['name']}  {space['state']}")
                             + f"  last used {space.get('lastUsedAt', '?')}" for space in data)

        emit(spaces, args.json, render)
        return EXIT_OK
    names = [space["name"] for space in spaces]
    if args.codespace_command == "stop":
        targets = [space["name"] for space in spaces if space.get("state") == "Available"] if args.all else [args.name] if args.name else []
        if not targets:
            print("nothing to stop" if args.all else "aq codespace stop: give NAME or --all", file=sys.stderr if not args.all else sys.stdout)
            return EXIT_OK if args.all else EXIT_USAGE
        worst = 0
        for name in targets:
            print(f"stopping {name}{' (dry run)' if args.dry_run else ''}")
            if not args.dry_run:
                worst = max(worst, run_live(["gh", "codespace", "stop", "-c", name]))
        return worst
    if args.name not in names:
        print(f"aq codespace delete: no Codespace {args.name!r}", file=sys.stderr)
        return EXIT_USAGE
    if args.dry_run:
        print(f"would delete {args.name}")
        return EXIT_OK
    if not confirm(f"delete Codespace {args.name} (its storage is gone for good)?", assume_yes=args.yes):
        return EXIT_USAGE
    return run_live(["gh", "codespace", "delete", "-c", args.name, "--force"])


# ---------------------------------------------------------------------------
# vault
# ---------------------------------------------------------------------------


def cmd_vault(args: argparse.Namespace) -> int:
    if (missing := needs_checkout()) is not None:
        return missing
    if args.vault_command == "record":
        command = [sys.executable, "scripts/vault_record.py", "--label", args.label, *[part for metric in args.metric or [] for part in ("--metric", metric)], *args.paths]
        if args.dry_run:
            print(" ".join(command))
            return EXIT_OK
        return run_live(command)
    vault = ROOT_DIR / "Aether-quant-Obsidian-Vault"
    if not vault.is_dir():
        print("aq vault graph: no Aether-quant-Obsidian-Vault/ in this checkout", file=sys.stderr)
        return EXIT_FAIL
    commands = [
        [sys.executable, "scripts/generate_code_graph.py", "--repo-root", "..", "--vault", "."],
        [sys.executable, "scripts/regenerate_vault.py", "--repo-root", "..", "--vault", ".", "--append-handoff", "--agent", args.agent, "--action", "completed",
         "--summary", args.summary, "--files", *args.files],
    ]
    for command in commands:
        print(" ".join(command))
        if not args.dry_run and (code := run_live(command, cwd=vault)) != 0:
            return code
    return EXIT_OK


# ---------------------------------------------------------------------------
# Problems.md
# ---------------------------------------------------------------------------

_PROBLEM_RE = re.compile(r"^### (\d+)([a-z]?)\. (.+?)\s*$", re.MULTILINE)


def parse_problems(text: str) -> list[dict]:
    """[{number, title, status, body}] from Problems.md's `### N. Title` entries."""
    matches = list(_PROBLEM_RE.finditer(text))
    out = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        body = text[match.end():end].strip()
        first = body.splitlines()[0] if body else ""
        status = "fixed" if "🟢" in first else "partial" if "🟡" in first else "closed" if "🔴" in first else "unknown"
        out.append({"number": f"{match.group(1)}{match.group(2)}", "title": match.group(3), "status": status, "body": body})
    return out


def next_problem_number(problems: Sequence[dict]) -> int:
    return max((int(re.match(r"\d+", problem["number"]).group(0)) for problem in problems), default=0) + 1


PROBLEM_TEMPLATE = """### {number}. <Title> ({version})
🟢 `fixed` · N/10

**Problem:** <1-3 sentences>

**Fix:** <1-3 sentences>

**Verification:** <1-3 sentences>
"""


def cmd_problems(args: argparse.Namespace) -> int:
    path = ROOT_DIR / "development" / "Problems.md"
    if not path.exists():
        print("aq problems: no development/Problems.md (a source checkout has it)", file=sys.stderr)
        return EXIT_FAIL
    problems = parse_problems(path.read_text(encoding="utf-8"))
    if args.problems_command == "next":
        number = next_problem_number(problems)
        emit({"next": number}, args.json, lambda data: PROBLEM_TEMPLATE.format(number=data["next"], version="V?.?.?"))
        return EXIT_OK
    if args.problems_command == "show":
        found = next((problem for problem in problems if problem["number"] == str(args.number)), None)
        if found is None:
            print(f"aq problems show: no #{args.number}", file=sys.stderr)
            return EXIT_FAIL
        emit(found, args.json, lambda data: f"### {data['number']}. {data['title']}\n{data['body']}")
        return EXIT_OK
    open_items = [problem for problem in problems if problem["status"] == "partial"]
    emit([{key: problem[key] for key in ("number", "title", "status")} for problem in open_items], args.json,
         lambda data: "\n".join(f"#{item['number']} {item['title']}" for item in data) or "no partial (🟡) problems")
    return EXIT_OK


# ---------------------------------------------------------------------------
# lint
# ---------------------------------------------------------------------------


def cmd_lint(args: argparse.Namespace) -> int:
    ruff = shutil.which("ruff")
    command = [ruff] if ruff else [sys.executable, "-m", "ruff"]
    code = run_live([*command, "check", ".", *(["--fix"] if args.fix else [])])
    if args.types and code == 0:
        if (missing := needs_checkout()) is not None:
            return missing
        code = run_live([sys.executable, "scripts/type_completeness.py"])
    return code


# ---------------------------------------------------------------------------
# config / lean diff
# ---------------------------------------------------------------------------


def leaf_items(node: Any, prefix: str = "") -> dict[str, Any]:
    """{dotted.path: leaf value} of a JSON tree (lists are leaves)."""
    if isinstance(node, dict) and node:
        out: dict[str, Any] = {}
        for key, value in node.items():
            out.update(leaf_items(value, f"{prefix}.{key}" if prefix else str(key)))
        return out
    return {prefix: node}


def leaf_diff(old: Any, new: Any) -> dict[str, list]:
    """{added: [[path, value]], removed: [[path, value]], changed: [[path, old, new]]} between two JSON trees."""
    before, after = leaf_items(old), leaf_items(new)
    return {
        "added": [[path, after[path]] for path in sorted(after.keys() - before.keys())],
        "removed": [[path, before[path]] for path in sorted(before.keys() - after.keys())],
        "changed": [[path, before[path], after[path]] for path in sorted(before.keys() & after.keys()) if before[path] != after[path]],
    }


def render_leaf_diff(diff: Mapping[str, list]) -> str:
    lines = [f"+ {path} = {json.dumps(value)}" for path, value in diff["added"]]
    lines += [f"- {path} = {json.dumps(value)}" for path, value in diff["removed"]]
    lines += [f"~ {path}: {json.dumps(old)} -> {json.dumps(new)}" for path, old, new in diff["changed"]]
    return "\n".join(lines) or "no differences"


def json_file_diff(path: Path, ref: str, root: Path = ROOT_DIR) -> dict[str, list] | None:
    """`path` against its version at git `ref`; None when git has no such version."""
    code, old_text = run_capture(["git", "show", f"{ref}:{path.relative_to(root).as_posix()}"], cwd=root)
    if code != 0:
        return None
    return leaf_diff(json.loads(old_text), json.loads(path.read_text(encoding="utf-8")))


def cmd_json_diff(path: Path, args: argparse.Namespace) -> int:
    diff = json_file_diff(path, args.ref)
    if diff is None:
        print(f"aq: git has no {path.name} at {args.ref}", file=sys.stderr)
        return EXIT_FAIL
    emit(diff, args.json, render_leaf_diff)
    return EXIT_OK


# ---------------------------------------------------------------------------
# the CLI's own reference, and the docs' links
# ---------------------------------------------------------------------------


def render_cli_markdown(parser: argparse.ArgumentParser) -> str:
    """Every command and subcommand with its usage line, description and flags, as Markdown for docs/reference/cli.md."""
    out = []
    for path, sub in walk_commands(parser):
        if not path:
            continue
        depth = min(len(path) + 2, 5)
        out.append(f"{'#' * depth} `aq {' '.join(path)}`\n")
        summary = _md_text(sub.description or "")
        if summary:
            out.append(summary + "\n")
        usage = " ".join(sub.format_usage().split())
        out.append(f"```text\n{usage.removeprefix('usage: ')}\n```\n")
        rows = []
        for action in sub._actions:
            if isinstance(action, (argparse._HelpAction, argparse._SubParsersAction)) or action.help == argparse.SUPPRESS:
                continue
            name = ", ".join(f"`{option}`" for option in action.option_strings) or f"`{action.dest}`"
            text = _md_text((action.help or "").replace("%%", "%").replace("|", "\\|"))
            rows.append(f"| {name} | {text} |")
        if rows:
            out.append("| Flag | Meaning |\n|---|---|\n" + "\n".join(rows) + "\n")
    return "\n".join(out).rstrip() + "\n"


def _md_text(text: str) -> str:
    """One line of help as Markdown text: `<run>` stays visible instead of becoming an HTML tag."""
    return " ".join(text.replace("<", "&lt;").replace(">", "&gt;").split())


_LINK_RE = re.compile(r"(?<!!)\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")


def markdown_anchors(text: str) -> set[str]:
    """GitHub-style anchors of every heading in `text`."""
    anchors = set()
    for heading in re.findall(r"^#{1,6}\s+(.+?)\s*#*$", text, re.MULTILINE):
        anchors.add(re.sub(r"[^\w\- ]", "", heading.strip().lower()).replace(" ", "-"))
    return anchors


def broken_links(paths: Iterable[Path], root: Path | None = None) -> list[str]:
    """`file: target` for every relative link whose file or anchor does not exist (external links are skipped)."""
    root = root or ROOT_DIR
    problems = []
    cache: dict[Path, set[str]] = {}
    for path in paths:
        text = path.read_text(encoding="utf-8")
        in_fence = False
        for line in text.splitlines():
            if line.lstrip().startswith("```"):
                in_fence = not in_fence
                continue
            if in_fence:
                continue
            for target in _LINK_RE.findall(re.sub(r"`[^`]*`", "", line)):
                if re.match(r"^[a-z][a-z0-9+.-]*:", target) or target.startswith("{{"):
                    continue
                file_part, _, anchor = target.partition("#")
                resolved = (path.parent / file_part).resolve() if file_part else path.resolve()
                if file_part and not resolved.exists():
                    problems.append(f"{path.relative_to(root).as_posix()}: {target}")
                    continue
                if anchor and resolved.suffix == ".md":
                    if resolved not in cache:
                        cache[resolved] = markdown_anchors(resolved.read_text(encoding="utf-8"))
                    if anchor.lower() not in cache[resolved]:
                        problems.append(f"{path.relative_to(root).as_posix()}: {target} (no such heading)")
    return problems


def link_docs(root: Path | None = None) -> list[Path]:
    root = root or ROOT_DIR
    paths = [root / "README.md", *sorted((root / "docs").rglob("*.md")), *sorted((root / "development").glob("*.md"))]
    paths += sorted(path for path in root.glob("*/README.md") if path.parent.name not in {"node_modules", "Aether-quant-Obsidian-Vault", "build", "site"})
    return [path for path in paths if path.exists()]


def external_links(paths: Iterable[Path]) -> list[str]:
    found = set()
    for path in paths:
        found |= {target for target in _LINK_RE.findall(path.read_text(encoding="utf-8")) if target.startswith(("http://", "https://"))}
    return sorted(found)


def check_external(url: str, timeout: float = 5.0) -> bool:
    import urllib.request

    request = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "aq-docs-links/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status < 400
    except Exception:  # any network failure counts as a broken link, reported, never raised
        return False


def cmd_docs_extra(args: argparse.Namespace) -> int:
    command = args.docs_command
    if command in {"build", "serve"}:
        if not shutil.which("mkdocs"):
            print('aq docs: mkdocs not found: pip install --require-hashes -r requirements/lock/docs.txt', file=sys.stderr)
            return EXIT_FAIL
        if command == "build":
            if (code := run_live([sys.executable, "scripts/build_docs.py"])) != 0:
                return code
            return run_live(["mkdocs", "build", *(["--strict"] if args.strict else [])])
        return run_live(["mkdocs", "serve", "--dev-addr", f"127.0.0.1:{args.port}"])
    if command == "cli":
        from docs_facts import apply_blocks, cli_reference_block

        page = ROOT_DIR / "docs" / "reference" / "cli.md"
        text = page.read_text(encoding="utf-8") if page.exists() else ""
        updated, moved = apply_blocks(text, {"CLI_REFERENCE": cli_reference_block()})
        if args.check:
            print("docs/reference/cli.md is current" if not moved else "docs/reference/cli.md is stale: aq docs cli")
            return EXIT_FAIL if moved else EXIT_OK
        if moved:
            page.write_text(updated, encoding="utf-8", newline="\n")
        print("docs/reference/cli.md " + ("updated" if moved else "already current"))
        return EXIT_OK
    paths = link_docs()
    problems = broken_links(paths)
    if args.external:
        problems += [f"external: {url}" for url in external_links(paths) if not check_external(url)]
    emit(problems, args.json, lambda data: "\n".join(data) or f"{len(paths)} docs: every relative link resolves")
    return EXIT_FAIL if problems else EXIT_OK


# ---------------------------------------------------------------------------
# bug report
# ---------------------------------------------------------------------------


def bug_report(root: Path = ROOT_DIR) -> str:
    """A Markdown report for a GitHub issue: versions and the doctor's results, with the home folder replaced by ~."""
    home = str(Path.home())
    packages = {}
    for name in ("numpy", "pandas", "torch", "lean", "fastapi"):
        try:
            packages[name] = _package_version(name)
        except PackageNotFoundError:
            packages[name] = "not installed"
    lines = ["<!-- aq bug-report: versions and environment checks only; no config values, environment variables or user names -->",
             "## Environment", "", f"- aq: {installed_version()}", f"- Python: {platform.python_version()}", f"- OS: {platform.platform()}"]
    lines += [f"- {name}: {value}" for name, value in packages.items()]
    lines += ["", "## aq doctor", "", "```text", render_checks(doctor_checks(root)), "```", "", "## What happened", "", "<steps, expected, actual>"]
    text = "\n".join(lines)
    text = text.replace(home, "~").replace(home.replace("\\", "/"), "~")
    user = os.environ.get("USERNAME") or os.environ.get("USER")
    return text.replace(user, "<user>") if user and len(user) > 2 else text


def cmd_bug_report(args: argparse.Namespace) -> int:
    text = re.sub(r"\x1b\[[0-9;]*m", "", bug_report())
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
        print(f"wrote {args.out}")
    else:
        print(text)
    return EXIT_OK


# ---------------------------------------------------------------------------
# examples and notebooks
# ---------------------------------------------------------------------------


def _docstring_line(path: Path) -> str:
    match = re.search(r'^\s*(?:"""|\'\'\')(.+?)$', path.read_text(encoding="utf-8"), re.MULTILINE)
    return match.group(1).strip().rstrip('."') if match else ""


def cmd_examples(args: argparse.Namespace) -> int:
    folder = ROOT_DIR / "examples"
    scripts = sorted(folder.glob("*.py")) if folder.is_dir() else []
    if args.examples_command == "list":
        emit([{"name": path.stem, "about": _docstring_line(path)} for path in scripts], args.json,
             lambda data: "\n".join(f"{item['name']}: {item['about']}" for item in data) or "no examples/ folder (a source checkout has it)")
        return EXIT_OK
    match = next((path for path in scripts if path.stem == args.name), None)
    if match is None:
        close = difflib.get_close_matches(args.name, [path.stem for path in scripts], n=3)
        print(f"aq examples run: no example {args.name!r}" + (f"; did you mean: {', '.join(close)}?" if close else ""), file=sys.stderr)
        return EXIT_USAGE
    return run_live([sys.executable, str(match)])


def notebook_title(path: Path) -> str:
    data = json.loads(path.read_text(encoding="utf-8"))
    for cell in data.get("cells", []):
        if cell.get("cell_type") == "markdown":
            text = "".join(cell.get("source", []))
            match = re.search(r"^#\s+(.+)$", text, re.MULTILINE)
            if match:
                return match.group(1).strip()
    return path.stem


def cmd_notebooks(args: argparse.Namespace) -> int:
    folder = ROOT_DIR / "docs" / "tutorials"
    books = sorted(folder.glob("*.ipynb")) if folder.is_dir() else []
    if args.notebooks_command == "list":
        emit([{"name": path.stem, "title": notebook_title(path)} for path in books], args.json,
             lambda data: "\n".join(f"{item['name']}: {item['title']}" for item in data) or "no docs/tutorials/ (a source checkout has it)")
        return EXIT_OK
    match = next((path for path in books if path.stem == args.name or path.stem.split("_", 1)[-1] == args.name), None)
    if match is None:
        print(f"aq notebooks run: no notebook {args.name!r} (aq notebooks list)", file=sys.stderr)
        return EXIT_USAGE
    try:
        import nbclient
        import nbformat
    except ImportError:
        print('aq notebooks run: needs the notebook tools: pip install "aether-quant[notebooks]"', file=sys.stderr)
        return EXIT_FAIL
    book = nbformat.read(str(match), as_version=4)
    nbclient.NotebookClient(book, timeout=600, kernel_name="python3", resources={"metadata": {"path": str(match.parent)}}).execute()
    out = Path(args.out) if args.out else None
    if out:
        nbformat.write(book, str(out))
        print(f"ran {match.name}, wrote {out}")
    else:
        print(f"ran {match.name}: every cell executed")
    return EXIT_OK


# ---------------------------------------------------------------------------
# phase check
# ---------------------------------------------------------------------------

MANUAL_PHASE_ITEMS = (
    "GitHub About: gh repo edit --description ... --homepage ... (when the book or the site moves)",
    "Older releases without assets: gh workflow run release.yml -f backfill_tag=vX.Y.Z",
    "Scorecard account checks: branch protection, code review, CII badge (owner decisions)",
    "Research Record / Backtest Statistics / long-window row / readiness block: only when a round, a Lean pin or a paper period happened",
)


def _script_ok(script: str, *args: str, root: Path = ROOT_DIR) -> tuple[bool, str]:
    code, out = run_capture([sys.executable, f"scripts/{script}", *args], cwd=root, timeout=600)
    return code == 0, (out.strip().splitlines() or [""])[-1][:160]


def phase_checks(version: str, root: Path = ROOT_DIR) -> list[dict]:
    """The automatic items of AGENTS.md's 'After every phase' and wrap-up lists."""
    checks = []
    changelog = (root / "development" / "Changelog.md").read_text(encoding="utf-8") if (root / "development" / "Changelog.md").exists() else ""
    checks.append(_check("Changelog phase", "ok" if f"## Phase {version}" in changelog else "fail", f"## Phase {version}", "add the phase to development/Changelog.md"))
    highlights = (root / "docs" / "about" / "changelog.md").read_text(encoding="utf-8") if (root / "docs" / "about" / "changelog.md").exists() else ""
    checks.append(_check("docs changelog highlights", "ok" if version in highlights else "fail", "docs/about/changelog.md", "write 3-6 highlight bullets"))
    todo = (root / "todo.md").read_text(encoding="utf-8") if (root / "todo.md").exists() else ""
    checks.append(_check("todo.md", "ok" if version in todo else "fail", "names the phase" if version in todo else "does not name the phase", "rewrite the current objective"))
    probe = ("import docs_facts, sys; r = docs_facts.sync_docs(docs_facts.tracked_docs(), docs_facts.compute_facts(), check=True, "
             "blocks=docs_facts.compute_blocks()); print(len(r['changed'])); sys.exit(1 if r['changed'] else 0)")
    code, out = run_capture([sys.executable, "-c", probe], cwd=root, timeout=600)
    checks.append(_check("doc facts", "ok" if code == 0 else "fail", "current" if code == 0 else f"{out.strip()} stale", "aq docs sync"))
    for script, label, args in (("scorecard_pins.py", "scorecard pins", ()), ("library_gate.py", "library gate", ()), ("formal_inventory.py", "formal inventory", ()),
                                ("readme_freshness.py", "README freshness", ())):
        if (root / "scripts" / script).exists():
            ok, detail = _script_ok(script, *args, root=root)
            checks.append(_check(label, "ok" if ok else "fail", detail, f"python scripts/{script}"))
    report = root / "coverage-report" / "coverage.json"
    if report.exists():
        summary = coverage_summary(json.loads(report.read_text(encoding="utf-8")), json_mtime=report.stat().st_mtime, root=root)
        ok = summary["percent"] == 100 and not summary["changed_since"] and not summary["below_100"]
        checks.append(_check("coverage 100%", "ok" if ok else "fail", f"{summary['percent']}%, {len(summary['changed_since'])} file(s) changed since", "aq test --coverage"))
    else:
        checks.append(_check("coverage 100%", "fail", "no coverage-report/coverage.json", "aq test --coverage"))
    _, porcelain = run_capture(["git", "status", "--porcelain"], cwd=root)
    checks.append(_check("clean tree", "ok" if not porcelain.strip() else "fail", f"{len(porcelain.splitlines())} changed file(s)", "commit (aq commit)"))
    if shutil.which("gh"):
        _, sha = run_capture(["git", "rev-parse", "HEAD"], cwd=root)
        runs = ci_runs(sha.strip())
        verdict = summarize_runs(runs)["verdict"] if runs is not None else "unknown"
        checks.append(_check("CI of HEAD", "ok" if verdict == "green" else "fail", verdict, "aq ci status --watch"))
        running = [space["name"] for space in codespaces() or [] if space.get("state") == "Available"]
        checks.append(_check("Codespaces stopped", "ok" if not running else "fail", ", ".join(running) or "none running", "aq codespace stop --all"))
    handoff = root / "Aether-quant-Obsidian-Vault" / "HANDOFF.md"
    today = _datetime.date.today().isoformat()
    if handoff.exists():
        checks.append(_check("vault handoff", "ok" if today in handoff.read_text(encoding="utf-8") else "fail", "an entry today" if today in handoff.read_text(encoding="utf-8") else "no entry today", "aq vault graph --summary ..."))
    checks += [_check(item.split(":")[0], "manual", item) for item in MANUAL_PHASE_ITEMS]
    return checks


def cmd_phase(args: argparse.Namespace) -> int:
    if (missing := needs_checkout()) is not None:
        return missing
    checks = phase_checks(args.version)

    def render(data: list) -> str:
        marks = {"ok": "✓", "fail": "✗", "manual": "·", "skip": "-"}
        return "\n".join(f"{marks.get(item['status'], '?')} {item['name']}: {item['detail']}" + (f"  -> {item['fix']}" if item["status"] == "fail" and item["fix"] else "") for item in data)

    emit(checks, args.json, render)
    return EXIT_GATE if any(check["status"] == "fail" for check in checks) else EXIT_OK


# ---------------------------------------------------------------------------
# scaffolding (aq scaffold module, aq test new)
# ---------------------------------------------------------------------------


def infer_group(module_path: str, groups: Iterable[str]) -> str:
    """The `_SUBSYSTEM_TEST_FILES` group a module's test belongs in: its top-level folder when that is a group, else meta."""
    parts = Path(module_path).parts
    known = set(groups)
    mapping = {"data_pipeline": "data-pipeline", "aq_devtools.py": "cli", "aq_lab_cli.py": "lab", "lab": "lab", "execution": "risk", "inference": "ml",
               "moe": "ml", "experts": "ml", "audit": "audit", "monitoring": "live", "notifications": "notifications"}
    head = parts[0] if parts else ""
    if head in known:
        return head
    if mapping.get(head) in known:
        return mapping[head]
    return "meta" if "meta" in known else sorted(known)[0]


def register_test_file(aq_cli_text: str, group: str, test_name: str) -> str:
    """`aq_cli.py`'s text with `test_name` added at the top of `group`'s list in `_SUBSYSTEM_TEST_FILES`."""
    if f'"{test_name}"' in aq_cli_text:
        return aq_cli_text
    start = aq_cli_text.index("_SUBSYSTEM_TEST_FILES: dict[str, list[str]] = {")
    key = f'    "{group}": [\n'
    index = aq_cli_text.index(key, start)
    insert = index + len(key)
    return aq_cli_text[:insert] + f'        "{test_name}",\n' + aq_cli_text[insert:]


def test_file_text(module: str, dotted: str) -> str:
    return f'''"""{module}: its own test file (AGENTS.md: one test file per source module)."""

from __future__ import annotations

import {dotted}  # noqa: F401


def test_write_the_first_test():
    assert False, "write the first test for {dotted}"
'''


def module_text(dotted: str) -> str:
    return f'''"""{dotted}: <one sentence on what this module does and why it exists>."""

from __future__ import annotations
'''


def add_py_module(pyproject_text: str, name: str) -> str:
    """pyproject's text with `name` added to `py-modules` (sorted), unchanged if it is there."""
    match = re.search(r"^py-modules = \[(.*?)\]$", pyproject_text, re.MULTILINE)
    if match is None:
        raise ValueError("pyproject.toml has no py-modules line")
    names = re.findall(r'"([^"]+)"', match.group(1))
    if name in names:
        return pyproject_text
    joined = ", ".join(f'"{item}"' for item in sorted([*names, name]))
    return pyproject_text[:match.start()] + f"py-modules = [{joined}]" + pyproject_text[match.end():]


def scaffold_test(module_path: str, *, group: str | None, root: Path = ROOT_DIR, dry_run: bool = False) -> tuple[int, list[str]]:
    """Create tests/test_<stem>.py for `module_path` and register it; returns (exit code, the actions taken)."""
    from aq_cli import _SUBSYSTEM_TEST_FILES

    posix = module_path.replace("\\", "/")
    stem = Path(posix).stem
    dotted = posix.removesuffix(".py").replace("/", ".")
    test_path = root / "tests" / f"test_{stem}.py"
    if test_path.exists():
        return EXIT_FAIL, [f"{test_path.relative_to(root).as_posix()} already exists"]
    chosen = group or infer_group(posix, _SUBSYSTEM_TEST_FILES)
    if chosen not in _SUBSYSTEM_TEST_FILES:
        return EXIT_USAGE, [f"no test group {chosen!r}; groups: {', '.join(_SUBSYSTEM_TEST_FILES)}"]
    actions = [f"create {test_path.relative_to(root).as_posix()}", f"register it under {chosen!r} in aq_cli.py"]
    if not dry_run:
        test_path.write_text(test_file_text(posix, dotted), encoding="utf-8", newline="\n")
        cli = root / "aq_cli.py"
        cli.write_text(register_test_file(cli.read_text(encoding="utf-8"), chosen, test_path.name), encoding="utf-8", newline="\n")
    return EXIT_OK, actions


def scaffold_module(module_path: str, *, group: str | None, root: Path = ROOT_DIR, dry_run: bool = False) -> tuple[int, list[str]]:
    posix = module_path.replace("\\", "/")
    if not posix.endswith(".py"):
        return EXIT_USAGE, ["give a path ending in .py, e.g. risk/my_rule.py"]
    target = root / posix
    if target.exists():
        return EXIT_FAIL, [f"{posix} already exists"]
    if not dry_run and not target.parent.is_dir():
        return EXIT_USAGE, [f"{target.parent.relative_to(root).as_posix()}/ does not exist"]
    actions = [f"create {posix}"]
    if not dry_run:
        target.write_text(module_text(posix.removesuffix(".py").replace("/", ".")), encoding="utf-8", newline="\n")
    if "/" not in posix:
        actions.append(f"add {Path(posix).stem!r} to pyproject.toml py-modules, then: pip install -e .")
        if not dry_run:
            pyproject = root / "pyproject.toml"
            pyproject.write_text(add_py_module(pyproject.read_text(encoding="utf-8"), Path(posix).stem), encoding="utf-8", newline="\n")
    code, more = scaffold_test(posix, group=group, root=root, dry_run=dry_run)
    actions += more
    actions += ["rule 14: export its public names from aether_quant/<subsystem>.py (or list them in tests/data/aether_quant_unexported.json with a reason)",
                f"add a line for it to {Path(posix).parent.as_posix() or '.'}/README.md"]
    return code, actions


def cmd_scaffold(args: argparse.Namespace) -> int:
    if (missing := needs_checkout()) is not None:
        return missing
    code, actions = scaffold_module(args.path, group=args.group, dry_run=args.dry_run)
    print("\n".join(("would " if args.dry_run else "") + action if action.startswith(("create", "register", "add ")) else action for action in actions))
    return code


# ---------------------------------------------------------------------------
# registration
# ---------------------------------------------------------------------------


def register(subparsers) -> None:
    """Add the developer commands to `aq`'s subparsers."""
    hooks = _parser(subparsers, "hooks", "The pre-commit gate: install it, show it, turn its coverage step off or on",
                    "aq hooks install", "aq hooks status", "aq hooks coverage off --once")
    hooks_sub = hooks.add_subparsers(dest="hooks_command", required=True, parser_class=type(hooks))
    install = _parser(hooks_sub, "install", "Install the wrapper in .git/hooks/pre-commit", "aq hooks install")
    add_dry_run_flag(install)
    status = _parser(hooks_sub, "status", "Whether the hook is installed, its gates, and the coverage switch", "aq hooks status --json")
    add_json_flag(status)
    coverage = _parser(hooks_sub, "coverage", "Turn the hook's coverage step off (--once: the next commit only), back on, or show it",
                       "aq hooks coverage off --once", "aq hooks coverage on")
    coverage.add_argument("coverage_action", choices=["off", "on", "status"])
    coverage.add_argument("--once", action="store_true", help="With off: skip only the next commit's coverage step")
    add_dry_run_flag(coverage)
    add_json_flag(coverage)
    hooks.set_defaults(func=cmd_hooks)

    commit = _parser(subparsers, "commit", "git commit through the pre-commit gate, optionally skipping its coverage step for this one commit",
                     'aq commit -m "fix the gate" --skip-coverage', 'aq commit -a -m "docs" -- --signoff')
    commit.add_argument("-m", "--message", required=True, help="The commit message")
    commit.add_argument("-a", "--all", action="store_true", help="Stage every tracked change first (git commit -a)")
    commit.add_argument("--skip-coverage", action="store_true", help="Skip the coverage step for this commit only (sets AQ_SKIP_COVERAGE_HOOK=1); the other gates still run")
    add_dry_run_flag(commit)
    commit.add_argument("git_args", nargs="*", help="More git commit arguments, after --")
    commit.set_defaults(func=cmd_commit)

    check = _parser(subparsers, "check", "Run the pre-commit gate now, committing nothing", "aq check", "aq check --no-coverage")
    check.add_argument("--no-coverage", action="store_true", help="Skip the coverage step")
    check.set_defaults(func=cmd_check)

    doctor = _parser(subparsers, "doctor", "Check the environment: Python, the install, tools, services, RAM, disk, model pins", "aq doctor", "aq doctor --json")
    add_json_flag(doctor)
    doctor.set_defaults(func=cmd_doctor)

    version = _parser(subparsers, "version", "The installed version, Python, platform and (in a checkout) the git commit", "aq version", "aq --version")
    add_json_flag(version)
    version.set_defaults(func=cmd_version)

    completion = _parser(subparsers, "completion", "Print a shell completion script", "aq completion powershell >> $PROFILE", "aq completion bash >> ~/.bashrc")
    completion.add_argument("shell", choices=["bash", "zsh", "powershell"])
    completion.set_defaults(func=cmd_completion)

    help_parser = _parser(subparsers, "help", "Help for a command (the same as aq COMMAND --help)", "aq help evaluate", "aq help hooks coverage")
    help_parser.add_argument("topic", nargs="*", help="The command path")
    help_parser.set_defaults(func=cmd_help)

    status_parser = _parser(subparsers, "status", "The project at a glance: branch, changes, hook and coverage, CI of HEAD, Dependabot, Codespaces",
                            "aq status", "aq status --offline", "aq status --git")
    add_json_flag(status_parser)
    status_parser.add_argument("--offline", action="store_true", help="Skip the GitHub queries (CI, PRs, Codespaces)")
    status_parser.add_argument("--git", action="store_true", help="Print plain git status instead")
    status_parser.set_defaults(func=cmd_status)

    ci = _parser(subparsers, "ci", "GitHub Actions: the runs of a commit, the failing lines of a run, or a ci.yml job run here",
                 "aq ci status --watch", "aq ci logs 44777003047", "aq ci local fast-guards")
    ci_sub = ci.add_subparsers(dest="ci_command", required=True, parser_class=type(ci))
    ci_status = _parser(ci_sub, "status", "Every workflow run of a commit: green, red (exit 1) or running (exit 3)", "aq ci status", "aq ci status --branch main --watch")
    ci_status.add_argument("--sha", default="HEAD", help="The commit (default HEAD)")
    ci_status.add_argument("--branch", default=None, help="The tip of this remote branch instead")
    ci_status.add_argument("--watch", action="store_true", help="Poll until nothing is running")
    ci_status.add_argument("--interval", type=int, default=30, help="Seconds between polls with --watch (default 30)")
    add_json_flag(ci_status)
    ci_logs = _parser(ci_sub, "logs", "The lines that explain each failed job of a run", "aq ci logs 44777003047", "aq ci logs 44777003047 --job python-compat")
    ci_logs.add_argument("run_id")
    ci_logs.add_argument("--job", default=None, help="Only jobs whose name contains this (default: every failed job)")
    ci_logs.add_argument("--lines", type=int, default=80, help="At most this many lines per job (default 80)")
    add_json_flag(ci_logs)
    ci_local = _parser(ci_sub, "local", "Run a workflow job's run: steps here, in order (uses: steps are skipped)", "aq ci local --list", "aq ci local fast-guards --dry-run")
    ci_local.add_argument("job", nargs="?", default=None, help="The job (omit or --list to list them)")
    ci_local.add_argument("--workflow", default="ci.yml", help="The workflow file under .github/workflows (default ci.yml)")
    ci_local.add_argument("--list", action="store_true", help="List the jobs and what each needs")
    ci_local.add_argument("--matrix", action="append", metavar="KEY=VALUE", help="A matrix value (default: each key's first)")
    add_dry_run_flag(ci_local)
    ci.set_defaults(func=cmd_ci)

    deps = _parser(subparsers, "deps", "Dependencies: Dependabot PRs, applying one correctly, the hash locks, pins, audit, why a package is locked",
                   "aq deps prs", "aq deps apply 57", "aq deps why numpy")
    deps_sub = deps.add_subparsers(dest="deps_command", required=True, parser_class=type(deps))
    prs = _parser(deps_sub, "prs", "Open Dependabot PRs: ecosystem, package, versions, checks", "aq deps prs --json")
    add_json_flag(prs)
    apply_parser = _parser(deps_sub, "apply", "Apply Dependabot PRs to the working tree (pip: re-lock with uv; npm: npm install); never commits",
                           "aq deps apply 53 55", "aq deps apply 57 --dry-run")
    apply_parser.add_argument("numbers", nargs="+", help="PR numbers")
    add_dry_run_flag(apply_parser)
    lock = _parser(deps_sub, "lock", "Rebuild requirements/lock/*.txt from their .in files (uv)", "aq deps lock", "aq deps lock --profile ci --upgrade-package numpy")
    lock.add_argument("--profile", action="append", help="One profile (repeatable; default all)")
    lock.add_argument("--upgrade-package", action="append", metavar="NAME", help="Let this pin move to its newest allowed version (repeatable)")
    _parser(deps_sub, "pins", "Every install pinned by hash (the Scorecard check); prints 0 when clean", "aq deps pins")
    _parser(deps_sub, "audit", "pip-audit over the runtime and ci locks (as CI's dependency-audit job)", "aq deps audit")
    why = _parser(deps_sub, "why", "Which packages pull PACKAGE into each lock", "aq deps why urllib3", "aq deps why numpy --profile light")
    why.add_argument("package")
    why.add_argument("--profile", action="append", help="Only this lock profile (repeatable)")
    add_json_flag(why)
    deps.set_defaults(func=cmd_deps)

    cov = _parser(subparsers, "coverage", "The last coverage run: totals, files below 100%, misses by function, cleaning",
                  "aq coverage report", "aq coverage misses --include \"risk/*\" --by-function")
    cov_sub = cov.add_subparsers(dest="coverage_command", required=True, parser_class=type(cov))
    report = _parser(cov_sub, "report", "Total, files below 100%, age, and files changed since (exit 3 below 100%)", "aq coverage report --json")
    add_json_flag(report)
    misses = _parser(cov_sub, "misses", "Uncovered lines, by file or function (scripts/coverage_misses.py)", "aq coverage misses --include lab/* --context 2")
    misses.add_argument("--include", action="append", help="Glob of files (repeatable)")
    misses.add_argument("--by-function", action="store_true", help="Group misses by function")
    misses.add_argument("--context", type=int, default=None, metavar="N", help="Print each miss with N lines around it")
    clean = _parser(cov_sub, "clean", "Delete coverage-report/ and .coverage* (dry run unless --apply)", "aq coverage clean --apply --yes")
    clean.add_argument("--apply", action="store_true", help="Delete (default: list only)")
    add_yes_flag(clean)
    add_json_flag(clean)
    cov.set_defaults(func=cmd_coverage)

    space = _parser(subparsers, "codespace", "GitHub Codespaces: list (running ones bill), stop, delete", "aq codespace list", "aq codespace stop --all")
    space_sub = space.add_subparsers(dest="codespace_command", required=True, parser_class=type(space))
    space_list = _parser(space_sub, "list", "Every Codespace and its state", "aq codespace list --json")
    add_json_flag(space_list)
    stop = _parser(space_sub, "stop", "Stop one Codespace, or every running one", "aq codespace stop --all", "aq codespace stop NAME")
    stop.add_argument("name", nargs="?", default=None)
    stop.add_argument("--all", action="store_true", help="Every running Codespace")
    add_dry_run_flag(stop)
    delete = _parser(space_sub, "delete", "Delete a Codespace and its storage (asks first)", "aq codespace delete NAME --yes")
    delete.add_argument("name")
    add_dry_run_flag(delete)
    add_yes_flag(delete)
    space.set_defaults(func=cmd_codespace)

    vault = _parser(subparsers, "vault", "Aether-Vault records and the Obsidian code graph", "aq vault record --label rules ml/evaluation/rules.json",
                    'aq vault graph --summary "V6.7.1 done" --files aq_cli.py')
    vault_sub = vault.add_subparsers(dest="vault_command", required=True, parser_class=type(vault))
    record = _parser(vault_sub, "record", "Record files in the vault with a label and metrics (scripts/vault_record.py)", "aq vault record --label freeze --metric trials=12 a.json")
    record.add_argument("--label", required=True, help="The record's tag")
    record.add_argument("--metric", action="append", help="key=value (repeatable)")
    record.add_argument("paths", nargs="+")
    add_dry_run_flag(record)
    graph = _parser(vault_sub, "graph", "Regenerate the Obsidian code graph and append a handoff entry", 'aq vault graph --summary "..." --files a.py b.py')
    graph.add_argument("--summary", required=True, help="The handoff summary")
    graph.add_argument("--files", nargs="+", required=True, help="Files the phase changed")
    graph.add_argument("--agent", default="ox-alpha", help="The handoff's agent name (default ox-alpha)")
    add_dry_run_flag(graph)
    vault.set_defaults(func=cmd_vault)

    problems = _parser(subparsers, "problems", "development/Problems.md: the next number and template, one entry, the partial ones", "aq problems next", "aq problems show 413")
    problems_sub = problems.add_subparsers(dest="problems_command", required=True, parser_class=type(problems))
    next_parser = _parser(problems_sub, "next", "The next free number and an entry template", "aq problems next")
    add_json_flag(next_parser)
    show = _parser(problems_sub, "show", "One entry", "aq problems show 413")
    show.add_argument("number")
    add_json_flag(show)
    open_parser = _parser(problems_sub, "open", "Entries still partial (🟡)", "aq problems open --json")
    add_json_flag(open_parser)
    problems.set_defaults(func=cmd_problems)

    lint = _parser(subparsers, "lint", "ruff over the project, optionally fixing, optionally the library's type completeness", "aq lint", "aq lint --fix --types")
    lint.add_argument("--fix", action="store_true", help="Apply ruff's safe fixes")
    lint.add_argument("--types", action="store_true", help="Also check the library's type completeness (scripts/type_completeness.py)")
    lint.set_defaults(func=cmd_lint)

    scaffold = _parser(subparsers, "scaffold", "Create a module with its registered test file and the reminders for the export and the readme",
                       "aq scaffold risk/my_rule.py", "aq scaffold my_tool.py --group meta --dry-run")
    scaffold.add_argument("path", help="The new module's path, e.g. risk/my_rule.py")
    scaffold.add_argument("--group", default=None, help="The test group (default: from the folder)")
    add_dry_run_flag(scaffold)
    scaffold.set_defaults(func=cmd_scaffold)

    phase = _parser(subparsers, "phase", "The end-of-phase checklist from AGENTS.md, checked where it can be", "aq phase check --version V6.7.1")
    phase_sub = phase.add_subparsers(dest="phase_command", required=True, parser_class=type(phase))
    phase_check = _parser(phase_sub, "check", "Changelog, docs, gates, coverage, tree, CI, Codespaces, vault (exit 3 on a failure)", "aq phase check --version V6.7.1 --json")
    phase_check.add_argument("--version", required=True, help="The phase as its Changelog heading names it")
    add_json_flag(phase_check)
    phase.set_defaults(func=cmd_phase)

    bug = _parser(subparsers, "bug-report", "A Markdown report for a GitHub issue: versions and the doctor's checks (no config, no env, no user names)",
                  "aq bug-report", "aq bug-report --out issue.md")
    bug.add_argument("--out", default=None, help="Write it here instead of printing")
    bug.set_defaults(func=cmd_bug_report)

    examples = _parser(subparsers, "examples", "The runnable examples in examples/", "aq examples list", "aq examples run aether_quant_quickstart")
    examples_sub = examples.add_subparsers(dest="examples_command", required=True, parser_class=type(examples))
    examples_list = _parser(examples_sub, "list", "Every example and what it shows", "aq examples list --json")
    add_json_flag(examples_list)
    examples_run = _parser(examples_sub, "run", "Run one example", "aq examples run aether_quant_quickstart")
    examples_run.add_argument("name")
    examples.set_defaults(func=cmd_examples)

    notebooks = _parser(subparsers, "notebooks", "The tutorial notebooks: list them, run one", "aq notebooks list", "aq notebooks run 00_hello_world --out done.ipynb")
    notebooks_sub = notebooks.add_subparsers(dest="notebooks_command", required=True, parser_class=type(notebooks))
    notebooks_list = _parser(notebooks_sub, "list", "Every tutorial and its title", "aq notebooks list --json")
    add_json_flag(notebooks_list)
    notebooks_run = _parser(notebooks_sub, "run", "Execute one tutorial", "aq notebooks run hello_world")
    notebooks_run.add_argument("name", help="The file name without .ipynb, or without its number prefix")
    notebooks_run.add_argument("--out", default=None, help="Write the executed notebook here")
    notebooks.set_defaults(func=cmd_notebooks)
