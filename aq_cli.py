"""`aq` — a thin convenience CLI wrapping Aether Quant's day-to-day commands.

Matches this codebase's existing CLI convention exactly (see
`retraining/orchestrator.py`'s `argparse` + `subparsers.add_parser(...)`
shape) - a single-file dispatcher, not a framework. Every subcommand other
than `trade-lock` is a thin `subprocess.run(...)` wrapper around a command
that already exists and is already documented elsewhere (README.md,
development/infrastructure.md) - no logic is reimplemented here, this file
only saves typing. `trade-lock` is the one exception: it calls
`risk/manual_override.py` directly, no subprocess.

Deliberately scoped for v1 - wraps the commands already in daily use, not
every command mentioned anywhere in the project. Designed to be extended
incrementally: add a new `subparsers.add_parser(...)` block plus one `elif`
branch in `main()` for each new command, following the existing pattern.

Install once (registers the `aq` command on PATH inside the active venv):
    pip install -e .
Then:
    aq --help
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from importlib.metadata import version as installed_version
from pathlib import Path

from risk.manual_override import read_manual_trade_lock_override, write_manual_trade_lock_override

ROOT_DIR = Path(__file__).resolve().parent
CONFIG_PATH = ROOT_DIR / "config.json"
WEBUI_DIR = ROOT_DIR / "webui"

PACKAGE_NAME = "aether-quant"
UPDATE_CACHE_PATH = Path.home() / ".aq" / "update_check.json"
UPDATE_CHECK_INTERVAL_SECONDS = 24 * 60 * 60
UPDATE_CHECK_TIMEOUT_SECONDS = 2


def _run(cmd: list[str], cwd: Path = ROOT_DIR) -> int:
    """Runs a command with inherited stdout/stderr (live output), returns its exit code."""
    result = subprocess.run(cmd, cwd=str(cwd))
    return result.returncode


def _find_quantconnect_lean_binary() -> str | None:
    """Plain `lean` on PATH is ambiguous on machines with `elan` (Lean 4, the
    theorem prover) installed - it ships its own `lean` binary under the same
    name as QuantConnect's Lean CLI (`pip install lean`). Disambiguate by
    checking `--version` output (Lean 4 prints "Lean (version 4...."; the
    QuantConnect CLI does not), preferring this repo's own venv first."""
    bin_dir_name = "Scripts" if sys.platform == "win32" else "bin"
    binary_name = "lean.exe" if sys.platform == "win32" else "lean"
    candidates = [str(ROOT_DIR / ".venv" / bin_dir_name / binary_name)]
    on_path = shutil.which("lean")
    if on_path:
        candidates.append(on_path)

    for candidate in candidates:
        if candidate != on_path and not Path(candidate).exists():
            continue
        try:
            result = subprocess.run([candidate, "--version"], capture_output=True, text=True, timeout=30)
        except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
            continue
        if "Lean (version" not in (result.stdout or "") + (result.stderr or ""):
            return candidate
    return None


def _parse_simple_version(value: str) -> tuple[int, ...] | None:
    """Best-effort "X.Y.Z" -> (X, Y, Z) parse. Returns None for anything that
    isn't a clean dotted-integer release version - dev/local builds (e.g.
    setuptools-scm's "0.1.dev35+gc744f9ca4.d20260704" fallback for untagged
    installs) simply never get flagged as outdated, which is the correct
    behavior here."""
    try:
        return tuple(int(part) for part in value.split("."))
    except ValueError:
        return None


def _read_update_cache() -> dict:
    if not UPDATE_CACHE_PATH.exists():
        return {}
    try:
        return json.loads(UPDATE_CACHE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _write_update_cache(latest_version: str) -> None:
    UPDATE_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {"last_checked": time.time(), "latest_version": latest_version}
    UPDATE_CACHE_PATH.write_text(json.dumps(payload), encoding="utf-8")


def _fetch_latest_version_from_pypi() -> str | None:
    try:
        url = f"https://pypi.org/pypi/{PACKAGE_NAME}/json"
        with urllib.request.urlopen(url, timeout=UPDATE_CHECK_TIMEOUT_SECONDS) as response:  # noqa: S310
            payload = json.loads(response.read().decode("utf-8"))
        return payload["info"]["version"]
    except Exception:
        return None


def _latest_known_version() -> str | None:
    cache = _read_update_cache()
    last_checked = cache.get("last_checked", 0)
    if time.time() - last_checked < UPDATE_CHECK_INTERVAL_SECONDS:
        return cache.get("latest_version")

    # Update the cache timestamp even on a failed fetch, so an offline user
    # doesn't pay the network timeout again on every single command - only
    # once per interval.
    latest = _fetch_latest_version_from_pypi()
    _write_update_cache(latest or cache.get("latest_version", ""))
    return latest or cache.get("latest_version")


def check_for_update() -> None:
    """Prints a one-line notice to stderr if a newer aether-quant release is
    available on PyPI. Never raises, never blocks a real command by more
    than the short network timeout, and only actually checks PyPI once per
    24h (cached in ~/.aq/update_check.json). Opt out with
    AQ_SKIP_UPDATE_CHECK=1 (e.g. for CI/scripted usage)."""
    if os.environ.get("AQ_SKIP_UPDATE_CHECK"):
        return
    try:
        installed = installed_version(PACKAGE_NAME)
        latest = _latest_known_version()
        if not latest:
            return
        installed_tuple = _parse_simple_version(installed)
        latest_tuple = _parse_simple_version(latest)
        if installed_tuple is None or latest_tuple is None:
            return
        if installed_tuple < latest_tuple:
            print(
                f"aq: a newer version is available ({latest}, you have {installed}) - "
                f"upgrade with: pip install --upgrade {PACKAGE_NAME}",
                file=sys.stderr,
            )
    except Exception:
        pass


def cmd_train(args: argparse.Namespace) -> int:
    cmd = [sys.executable, "train.py"]
    if args.dataset_only:
        cmd.append("--dataset-only")
    elif args.init_only:
        cmd.append("--init-only")
    elif args.experts_only:
        cmd.append("--experts-only")
    return _run(cmd)


def cmd_test(_args: argparse.Namespace) -> int:
    return _run([sys.executable, "-m", "pytest", "tests/"])


def cmd_backtest(_args: argparse.Namespace) -> int:
    lean_binary = _find_quantconnect_lean_binary()
    if lean_binary is None:
        print("error: QuantConnect Lean CLI not found (checked .venv and PATH).", file=sys.stderr)
        return 1
    return _run([lean_binary, "backtest", "."])


def cmd_report(args: argparse.Namespace) -> int:
    lean_binary = _find_quantconnect_lean_binary()
    if lean_binary is None:
        print("error: QuantConnect Lean CLI not found (checked .venv and PATH).", file=sys.stderr)
        return 1
    backtest_dir = ROOT_DIR / "backtests" / args.backtest_dir
    return _run(
        [
            lean_binary,
            "report",
            "--backtest-results",
            str(backtest_dir / f"{args.result_id}.json"),
            "--report-destination",
            str(backtest_dir / "report.html"),
            "--overwrite",
        ]
    )


def cmd_api(_args: argparse.Namespace) -> int:
    return _run([sys.executable, "-m", "uvicorn", "monitoring.api_server:app", "--port", "8001", "--reload"])


def cmd_webui(_args: argparse.Namespace) -> int:
    npm = "npm.cmd" if sys.platform == "win32" else "npm"
    return _run([npm, "run", "dev"], cwd=WEBUI_DIR)


def cmd_docker_up(args: argparse.Namespace) -> int:
    if args.all:
        services = [
            "redis",
            "postgres",
            "aether-quant",
            "experience-worker",
            "performance-trigger-worker",
            "retraining-worker",
            "telegram-worker",
        ]
        return _run(["docker", "compose", "up", "-d", *services])
    if args.lean:
        return _run(["docker", "compose", "--profile", "lean", "up", "-d"])
    return _run(["docker", "compose", "up", "-d", "redis", "postgres"])


def cmd_docker_build(_args: argparse.Namespace) -> int:
    return _run(["docker", "compose", "build", "aether-quant"])


def cmd_retrain(args: argparse.Namespace) -> int:
    return _run([sys.executable, "-m", "retraining.orchestrator", args.stage, *args.retrain_args])


def cmd_paper_readiness(_args: argparse.Namespace) -> int:
    return _run([sys.executable, "-m", "execution.paper_readiness_report"])


def cmd_trade_lock(args: argparse.Namespace) -> int:
    if args.on:
        write_manual_trade_lock_override(True, CONFIG_PATH)
        print("Trade lock override: ON (trading forced paused).")
    elif args.off:
        write_manual_trade_lock_override(False, CONFIG_PATH)
        print("Trade lock override: OFF (trading forced resumed, even past a sticky total-drawdown lock).")
    elif args.auto:
        write_manual_trade_lock_override(None, CONFIG_PATH)
        print("Trade lock override: AUTO (back to today's default automatic behavior).")
    else:  # status
        override = read_manual_trade_lock_override(CONFIG_PATH)
        label = {True: "ON (forced paused)", False: "OFF (forced resumed)", None: "AUTO (automatic behavior)"}[override]
        print(f"Trade lock override: {label}")
    return 0


def cmd_status(_args: argparse.Namespace) -> int:
    return _run(["git", "status"])


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="aq", description="Aether Quant convenience CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    train_parser = subparsers.add_parser("train", help="Run the training pipeline (wraps python train.py)")
    train_group = train_parser.add_mutually_exclusive_group()
    train_group.add_argument("--dataset-only", action="store_true", help="Build dataset/scaler/manifest only")
    train_group.add_argument("--init-only", action="store_true", help="Refresh the data inventory only")
    train_group.add_argument("--experts-only", action="store_true", help="Train the 4 expert models only")
    train_parser.set_defaults(func=cmd_train)

    test_parser = subparsers.add_parser("test", help="Run the test suite (wraps pytest tests/)")
    test_parser.set_defaults(func=cmd_test)

    backtest_parser = subparsers.add_parser("backtest", help="Run a Lean backtest (wraps lean backtest .)")
    backtest_parser.set_defaults(func=cmd_backtest)

    report_parser = subparsers.add_parser("report", help="Generate a Lean HTML report for a finished backtest")
    report_parser.add_argument("backtest_dir", help="Folder name under backtests/, e.g. 2026-07-04_13-06-51")
    report_parser.add_argument("result_id", help="Result JSON id, e.g. 1366365999")
    report_parser.set_defaults(func=cmd_report)

    api_parser = subparsers.add_parser("api", help="Start the FastAPI monitoring server on :8001")
    api_parser.set_defaults(func=cmd_api)

    webui_parser = subparsers.add_parser("webui", help="Start the webui dev server (npm run dev)")
    webui_parser.set_defaults(func=cmd_webui)

    docker_parser = subparsers.add_parser("docker", help="Docker Compose shortcuts")
    docker_subparsers = docker_parser.add_subparsers(dest="docker_command", required=True)

    docker_up_parser = docker_subparsers.add_parser("up", help="Start infra services")
    docker_up_group = docker_up_parser.add_mutually_exclusive_group()
    docker_up_group.add_argument("--lean", action="store_true", help="Start via the lean Compose profile")
    docker_up_group.add_argument("--all", action="store_true", help="Start the full stack, including all workers")
    docker_up_parser.set_defaults(func=cmd_docker_up)

    docker_build_parser = docker_subparsers.add_parser("build", help="Rebuild the aether-quant app image")
    docker_build_parser.set_defaults(func=cmd_docker_build)

    retrain_parser = subparsers.add_parser(
        "retrain", help="Thin dispatcher to python -m retraining.orchestrator <stage> ..."
    )
    retrain_parser.add_argument(
        "stage",
        choices=["plan", "train", "train_topology", "validate", "backtest", "commit", "promote", "rollback", "status"],
    )
    retrain_parser.add_argument("retrain_args", nargs=argparse.REMAINDER, help="Passed through verbatim, e.g. --version-id <uuid>")
    retrain_parser.set_defaults(func=cmd_retrain)

    paper_readiness_parser = subparsers.add_parser(
        "paper-readiness", help="Check whether the system is ready for phase_v2.runtime.mode='paper'"
    )
    paper_readiness_parser.set_defaults(func=cmd_paper_readiness)

    trade_lock_parser = subparsers.add_parser(
        "trade-lock", help="Manually override the sticky total-drawdown trade lock"
    )
    trade_lock_group = trade_lock_parser.add_mutually_exclusive_group(required=True)
    trade_lock_group.add_argument("--on", action="store_true", help="Force trading paused")
    trade_lock_group.add_argument("--off", action="store_true", help="Force trading resumed")
    trade_lock_group.add_argument("--auto", action="store_true", help="Return to fully automatic behavior")
    trade_lock_group.add_argument("--status", dest="status", action="store_true", help="Print the current override state")
    trade_lock_parser.set_defaults(func=cmd_trade_lock)

    status_parser = subparsers.add_parser("status", help="Show git status")
    status_parser.set_defaults(func=cmd_status)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    exit_code = args.func(args)
    check_for_update()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
