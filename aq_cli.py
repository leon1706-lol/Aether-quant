"""`aq` — a thin convenience CLI wrapping Aether Quant's day-to-day commands.

Matches this codebase's existing CLI convention exactly (see
`retraining/orchestrator.py`'s `argparse` + `subparsers.add_parser(...)`
shape) - a single-file dispatcher, not a framework. Every subcommand other
than `trade-lock` and `fetch` is a thin `subprocess.run(...)` wrapper around
a command that already exists and is already documented elsewhere
(README.md, development/infrastructure.md) - no logic is reimplemented
here, this file only saves typing. `trade-lock` and `fetch` are the two
exceptions: they call `risk/manual_override.py` and
`data_pipeline/fetch.py` directly, in-process, no subprocess.

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
import re
import shutil
import subprocess
import sys
import time
import urllib.request
import uuid
from collections.abc import Iterator
from datetime import date
from importlib.metadata import version as installed_version
from pathlib import Path

from data_pipeline.fetch import ASSET_CLASSES, fetch_adhoc_asset
from data_pipeline.ib_backfill import (
    IBNotConfiguredError,
    attempt_connection,
    connect_ib,
    disconnect_ib,
    fetch_future_historical_bars,
    fetch_option_historical_bars,
    ib_readiness_status,
    load_futures_contract_specs,
)
from risk.manual_override import read_manual_trade_lock_override, write_manual_trade_lock_override

IB_ASSET_CLASSES = ("futures", "options")

ROOT_DIR = Path(__file__).resolve().parent
CONFIG_PATH = ROOT_DIR / "config.json"
LEAN_JSON_PATH = ROOT_DIR / "lean.json"
WEBUI_DIR = ROOT_DIR / "webui"
README_PATH = ROOT_DIR / "README.md"

PACKAGE_NAME = "aether-quant"
UPDATE_CACHE_PATH = Path.home() / ".aq" / "update_check.json"
UPDATE_CHECK_INTERVAL_SECONDS = 24 * 60 * 60
UPDATE_CHECK_TIMEOUT_SECONDS = 2

_ANSI_ESCAPE_PATTERN = re.compile(r"\x1b\[[0-9;]*m")
_TEST_BADGE_MARKER_START = "<!-- AQ:TEST_BADGE_START -->"
_TEST_BADGE_MARKER_END = "<!-- AQ:TEST_BADGE_END -->"


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


def _iso_date(value: str) -> str:
    """Validates --start/--end as strict ISO 8601 YYYY-MM-DD, matching the
    convention used everywhere else in this repo (config.json,
    yfinance_backfill.py) - rejects other formats (e.g. DD.MM.YYYY) with a
    clear error instead of a confusing downstream yfinance failure."""
    try:
        date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid date {value!r} - expected ISO 8601 YYYY-MM-DD") from exc
    return value


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
    if args.gating_only:
        return _train_gating_only()
    if args.multitask_only:
        return _train_multitask_only()
    if args.sequence_only:
        return _train_sequence_only()
    cmd = [sys.executable, "train.py"]
    if args.dataset_only:
        cmd.append("--dataset-only")
    elif args.init_only:
        cmd.append("--init-only")
    elif args.experts_only:
        cmd.append("--experts-only")
    elif args.walk_forward:
        cmd.append("--walk-forward")
        if args.step_days is not None:
            cmd += ["--step-days", str(args.step_days)]
        if args.mode is not None:
            cmd += ["--mode", args.mode]
    return _run(cmd)


def _train_gating_only() -> int:
    """`aq train --gating-only`: trains the learned gating blend
    (train_gating.py) and installs it straight into active ml/, mirroring
    what `train.py --experts-only` already does for the expert models.

    train_gating.py always writes to ml/versions/<version_id>/ (same
    versioned-candidate convention every other trainer in this project
    uses), so this generates a throwaway version-id, runs the trainer,
    then copies the 3 resulting artifacts into active ml/ - the same
    manual promotion-simulation step already documented for verifying this
    trainer, skipping the full retraining/validate/backtest/commit/promote
    pipeline since this is an ad-hoc, user-triggered run, not a scheduled
    candidate."""
    version_id = f"gating-only-{uuid.uuid4()}"
    returncode = _run([sys.executable, "train_gating.py", "--version-id", version_id])
    if returncode != 0:
        return returncode

    version_dir = ROOT_DIR / "ml" / "versions" / version_id
    artifact_names = ("gating_model.json", "gating_feature_schema.json", "gating_training_metrics.json")
    if any(not (version_dir / name).exists() for name in artifact_names):
        print(
            "aq train --gating-only: train_gating.py exited 0 but skipped writing artifacts "
            "(likely insufficient validation/backtest rows) - active ml/ left unchanged.",
            file=sys.stderr,
        )
        return 0

    ml_dir = ROOT_DIR / "ml"
    for name in artifact_names:
        shutil.copy2(version_dir / name, ml_dir / name)
    print(f"aq train --gating-only: copied {', '.join(artifact_names)} into active ml/.")
    return 0


def _train_multitask_only() -> int:
    """`aq train --multitask-only`: trains the joint direction+magnitude+
    volatility model (train_multitask.py) and installs it straight into
    active ml/ - identical shape to _train_gating_only() above, including
    the throwaway version-id / manual promotion-simulation / "skipped must
    never look like failed" handling."""
    version_id = f"multitask-only-{uuid.uuid4()}"
    returncode = _run([sys.executable, "train_multitask.py", "--version-id", version_id])
    if returncode != 0:
        return returncode

    version_dir = ROOT_DIR / "ml" / "versions" / version_id
    artifact_names = ("multitask_model.json", "multitask_feature_schema.json", "multitask_training_metrics.json")
    if any(not (version_dir / name).exists() for name in artifact_names):
        print(
            "aq train --multitask-only: train_multitask.py exited 0 but skipped writing artifacts "
            "(likely insufficient train/validation/backtest rows) - active ml/ left unchanged.",
            file=sys.stderr,
        )
        return 0

    ml_dir = ROOT_DIR / "ml"
    for name in artifact_names:
        shutil.copy2(version_dir / name, ml_dir / name)
    print(f"aq train --multitask-only: copied {', '.join(artifact_names)} into active ml/.")
    return 0


def _train_sequence_only() -> int:
    """`aq train --sequence-only`: trains the Phase 2 causal-TCN sequence
    encoder (train_sequence.py) and installs it straight into active ml/ -
    identical shape to _train_multitask_only()/_train_gating_only() above."""
    version_id = f"sequence-only-{uuid.uuid4()}"
    returncode = _run([sys.executable, "train_sequence.py", "--version-id", version_id])
    if returncode != 0:
        return returncode

    version_dir = ROOT_DIR / "ml" / "versions" / version_id
    artifact_names = ("sequence_model.json", "sequence_feature_schema.json", "sequence_training_metrics.json")
    if any(not (version_dir / name).exists() for name in artifact_names):
        print(
            "aq train --sequence-only: train_sequence.py exited 0 but skipped writing artifacts "
            "(likely insufficient train/validation/backtest rows) - active ml/ left unchanged.",
            file=sys.stderr,
        )
        return 0

    ml_dir = ROOT_DIR / "ml"
    for name in artifact_names:
        shutil.copy2(version_dir / name, ml_dir / name)
    print(f"aq train --sequence-only: copied {', '.join(artifact_names)} into active ml/.")
    return 0


def _update_readme_test_badge(passed: int, failed: int) -> None:
    """Atomically rewrites the shields.io test-count badge between the
    AQ:TEST_BADGE markers in README.md, so it never drifts from the real
    pass count. Mirrors the equivalent mechanism in the sibling Aether-Vault
    project's `av test`. Never raises - a badge-update bug must never fail
    `aq test` itself."""
    total = passed + failed
    if total == 0:
        return  # nothing collected - leave the badge alone rather than zero it out
    if not README_PATH.is_file():
        return
    text = README_PATH.read_text(encoding="utf-8")
    if _TEST_BADGE_MARKER_START not in text or _TEST_BADGE_MARKER_END not in text:
        return

    color = "brightgreen" if failed == 0 else "red"
    badge = (
        f'<img src="https://img.shields.io/badge/tests-{passed}%2F{total}%20passing-{color}'
        f'?style=flat-square&labelColor=1A1A1A" alt="{passed} of {total} tests passing">'
    )
    pattern = re.compile(re.escape(_TEST_BADGE_MARKER_START) + r".*?" + re.escape(_TEST_BADGE_MARKER_END), re.DOTALL)
    replacement = f"{_TEST_BADGE_MARKER_START}{badge}{_TEST_BADGE_MARKER_END}"
    updated_text = pattern.sub(replacement, text, count=1)
    if updated_text == text:
        return

    tmp_path = README_PATH.with_suffix(README_PATH.suffix + ".tmp")
    tmp_path.write_text(updated_text, encoding="utf-8")
    tmp_path.replace(README_PATH)
    print(f"Updated README.md test badge: {passed}/{total} passing")


def _run_captured(cmd: list[str], cwd: Path = ROOT_DIR) -> tuple[int, str]:
    """Like _run(), but also captures combined stdout+stderr while still
    streaming it live to the terminal - used only by cmd_test, which needs
    the captured text afterward to parse the real pass/fail count for the
    README badge. Kept as its own function, separate from _run() (every
    other subprocess-wrapping command's single choke point - see this
    module's test file docstring), specifically so tests can mock this one
    choke point without silently falling through to a real subprocess call
    the way mocking only `_run` would (that exact gap previously let
    `aq test`'s own test recursively spawn a real, full pytest run on every
    invocation of the suite)."""
    process = subprocess.Popen(
        cmd,
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    output_lines = []
    for line in process.stdout:
        print(line, end="")
        output_lines.append(line)
    process.wait()
    return process.returncode, "".join(output_lines)


def cmd_test(_args: argparse.Namespace) -> int:
    """Runs pytest with live-streamed output (same UX as a plain
    subprocess.run), while also capturing it so the real pass/fail count can
    be parsed afterward and used to refresh README.md's test badge - mirrors
    the sibling Aether-Vault project's `av test` exactly."""
    exit_code, output = _run_captured([sys.executable, "-m", "pytest", "tests/", "--color=yes"])

    captured = _ANSI_ESCAPE_PATTERN.sub("", output)
    passed_match = re.search(r"(\d+) passed", captured)
    failed_match = re.search(r"(\d+) failed", captured)
    error_match = re.search(r"(\d+) error", captured)
    if passed_match:
        passed = int(passed_match.group(1))
        failed = (int(failed_match.group(1)) if failed_match else 0) + (int(error_match.group(1)) if error_match else 0)
        _update_readme_test_badge(passed, failed)

    return exit_code


def cmd_backtest(_args: argparse.Namespace) -> int:
    lean_binary = _find_quantconnect_lean_binary()
    if lean_binary is None:
        print("error: QuantConnect Lean CLI not found (checked .venv and PATH).", file=sys.stderr)
        return 1
    exit_code = _run([lean_binary, "backtest", "."])
    if exit_code == 0:
        try:
            from generate_backtest_report import update_readme_from_latest_backtest

            if update_readme_from_latest_backtest():
                print("Updated README.md's Backtest Results section.")
        except Exception as error:  # noqa: BLE001 - must never fail the backtest command itself
            print(f"warning: failed to update README.md's backtest results ({error})", file=sys.stderr)
    return exit_code


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


class ConfigPathError(Exception):
    """Raised by _get_config_value/_set_config_value for a bad dotted path."""


def _get_config_value(config: dict, dotted_path: str) -> object:
    node = config
    walked: list[str] = []
    for segment in dotted_path.split("."):
        walked.append(segment)
        if not isinstance(node, dict) or segment not in node:
            raise ConfigPathError(f"no such config key: {'.'.join(walked)!r}")
        node = node[segment]
    return node


def _coerce_config_value(raw: str) -> object:
    """JSON-first parsing so true/false/123/0.5/[...]/{...} all become their
    real type automatically; anything that isn't valid JSON on its own
    (e.g. a bare word) is kept as a plain string."""
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def _set_config_value(config: dict, dotted_path: str, raw_value: str) -> tuple[object, object, bool]:
    """Mutates `config` in place. Returns (old_value, new_value, type_changed) -
    deliberately does not refuse to overwrite a list/dict: the caller wants
    full read/write access to every key, not just scalars. Safety instead
    comes from always reporting old -> new (and a type-change warning) to
    the caller, plus the automatic config.json.bak snapshot cmd_config()
    writes before every set."""
    *parents, leaf = dotted_path.split(".")
    node = config
    for segment in parents:
        if not isinstance(node, dict) or segment not in node:
            raise ConfigPathError(f"no such config key: {dotted_path!r}")
        node = node[segment]
    if not isinstance(node, dict) or leaf not in node:
        raise ConfigPathError(f"no such config key: {dotted_path!r}")
    old_value = node[leaf]
    new_value = _coerce_config_value(raw_value)
    node[leaf] = new_value
    return old_value, new_value, type(old_value) is not type(new_value)


def _iter_leaf_paths(node: object, prefix: str = "") -> Iterator[str]:
    """Recursively yields every dot-joined leaf path under `node`. A "leaf"
    is any non-dict value (or an empty dict) - list-valued keys show up as
    one leaf, never expanded per-element."""
    if isinstance(node, dict) and node:
        for key, value in node.items():
            yield from _iter_leaf_paths(value, f"{prefix}.{key}" if prefix else key)
    else:
        yield prefix


def _dispatch_json_config_command(args: argparse.Namespace, json_path: Path, command_attr: str) -> int:
    """Shared dispatch for `aq config`/`aq lean` - both are the same
    dump/get/set/keys tool over a single flat JSON file, just pointed at a
    different path. See cmd_config()/cmd_lean()."""
    data = json.loads(json_path.read_text(encoding="utf-8"))
    command = getattr(args, command_attr, None)

    try:
        if command is None:
            print(json.dumps(data, indent=2))
            return 0

        if command == "get":
            value = _get_config_value(data, args.dotted_path)
            print(value if isinstance(value, str) else json.dumps(value, indent=2))
            return 0

        if command == "keys":
            root = _get_config_value(data, args.dotted_prefix) if args.dotted_prefix else data
            for path in _iter_leaf_paths(root, args.dotted_prefix or ""):
                print(path)
            return 0

        if command == "set":
            shutil.copy2(json_path, json_path.with_suffix(".json.bak"))
            old_value, new_value, type_changed = _set_config_value(data, args.dotted_path, args.value)
            json_path.write_text(json.dumps(data, indent=4) + "\n", encoding="utf-8")
            print(f"{args.dotted_path}: {old_value!r} -> {new_value!r}")
            if type_changed:
                print(
                    f"WARNING: type changed from {type(old_value).__name__} to {type(new_value).__name__} "
                    f"for {args.dotted_path}",
                    file=sys.stderr,
                )
            return 0
    except ConfigPathError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    return 1


def cmd_config(args: argparse.Namespace) -> int:
    return _dispatch_json_config_command(args, CONFIG_PATH, "config_command")


def cmd_lean(args: argparse.Namespace) -> int:
    return _dispatch_json_config_command(args, LEAN_JSON_PATH, "lean_command")

    return 1


def cmd_fetch(args: argparse.Namespace) -> int:
    ib = None
    fetch_fn = None
    if args.asset_class in IB_ASSET_CLASSES:
        if args.expiry is None:
            print(f"error: --expiry is required for asset_class={args.asset_class!r}", file=sys.stderr)
            return 1
        if args.asset_class == "options" and (args.strike is None or args.right is None):
            print("error: --strike and --right are required for asset_class='options'", file=sys.stderr)
            return 1

        config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        lean_config = json.loads(LEAN_JSON_PATH.read_text(encoding="utf-8"))
        try:
            ib = connect_ib(config, lean_config)
        except IBNotConfiguredError as error:
            print(f"error: {error}", file=sys.stderr)
            return 1

        if args.asset_class == "futures":
            contract_spec = load_futures_contract_specs().get(args.ticker.upper(), {})
            fetch_fn = lambda symbol, start, end: fetch_future_historical_bars(ib, symbol, contract_spec, start, end)  # noqa: E731
        else:
            fetch_fn = lambda symbol, start, end: fetch_option_historical_bars(  # noqa: E731
                ib, symbol, args.expiry, args.strike, args.right, start, end
            )

    try:
        fetch_kwargs = {"fetch_fn": fetch_fn} if fetch_fn is not None else {}
        report = fetch_adhoc_asset(args.asset_class, args.ticker, args.start, args.end, apply=args.apply, **fetch_kwargs)
    finally:
        if ib is not None:
            disconnect_ib(ib)

    label = "APPLY" if args.apply else "DRY RUN"
    print(f"{label} — {report['ticker']} ({report['yahoo_symbol']}): {report['action']}, rows_fetched={report['rows_fetched']}")
    if report["suggested_available_from"]:
        print(f"    date range fetched: {report['suggested_available_from']} .. {report['suggested_available_to']}")
    print(f"    data_path: {report['data_path']}")

    if report["config_status"] == "added":
        print(f"    config.json: added a new {report['ticker']} asset block to phase1.universe.assets[]")
    elif report["config_status"] == "already_exists":
        print(
            f"    config.json: {report['ticker']} is already configured - left untouched. "
            "Use data_pipeline/yfinance_backfill.py to extend an existing asset's date range instead."
        )

    if not args.apply:
        print("\nDry run only — nothing was written. Re-run with --apply to write the zip file and update config.json.")
    elif report["action"] == "written":
        print("\nReady to prepare training: run `python train.py --dataset-only` to confirm this ticker's asset quality, then `python train.py` when ready.")

    return 1 if report["action"] == "no_data_returned" else 0


def cmd_ib(_args: argparse.Namespace) -> int:
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    lean_config = json.loads(LEAN_JSON_PATH.read_text(encoding="utf-8"))
    status = ib_readiness_status(config, lean_config)

    if status == "disabled":
        print("IB: disabled (phase_v2.ib.enabled is false)")
        print("    Enable with: aq config set phase_v2.ib.enabled true")
        return 0

    if status == "enabled_but_lean_credentials_missing":
        print("IB: enabled in config.json, but lean.json's IB credentials are not filled in")
        print("    Set them with: aq lean set ib-account <ACCOUNT>  and  aq lean set ib-user-name <USERNAME>")
        return 1

    reachable, detail = attempt_connection(config, lean_config)
    if reachable:
        print(f"IB: {detail} (connected to {config['phase_v2']['ib'].get('host')}:{config['phase_v2']['ib'].get('port')})")
        return 0

    print(f"IB: enabled and credentialed, but not reachable — {detail}")
    print("    Check that TWS or IB Gateway is running and logged in on the configured host/port.")
    return 1


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
    train_group.add_argument(
        "--gating-only", action="store_true", help="Train the learned gating blend only (wraps python train_gating.py)"
    )
    train_group.add_argument(
        "--multitask-only",
        action="store_true",
        help="Train the joint direction+magnitude+volatility model only (wraps python train_multitask.py)",
    )
    train_group.add_argument(
        "--sequence-only",
        action="store_true",
        help="Train the Phase 2 causal-TCN sequence encoder only (wraps python train_sequence.py)",
    )
    train_group.add_argument(
        "--walk-forward",
        action="store_true",
        help=(
            "Phase 4 of the 5/10 -> 9/10 roadmap: run the dataset-build + training pipeline once per "
            "walk-forward window (wraps python train.py --walk-forward). Never touches active ml/ - "
            "diagnostic only, writes to ml/versions/<run-id>/window_<i>/."
        ),
    )
    train_parser.add_argument(
        "--step-days", type=int, default=None, help="Walk-forward step size in days (only with --walk-forward)."
    )
    train_parser.add_argument(
        "--mode",
        type=str,
        choices=("rolling", "expanding"),
        default=None,
        help="Walk-forward mode: rolling or expanding (only with --walk-forward).",
    )
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

    config_parser = subparsers.add_parser("config", help="Show or edit config.json")
    config_parser.set_defaults(func=cmd_config)
    config_subparsers = config_parser.add_subparsers(dest="config_command")

    config_get_parser = config_subparsers.add_parser("get", help="Print a config.json value")
    config_get_parser.add_argument("dotted_path")

    config_keys_parser = config_subparsers.add_parser("keys", help="List leaf key paths (optionally scoped to a prefix)")
    config_keys_parser.add_argument("dotted_prefix", nargs="?", default=None)

    config_set_parser = config_subparsers.add_parser("set", help="Set a config.json value (JSON-parsed, string fallback)")
    config_set_parser.add_argument("dotted_path")
    config_set_parser.add_argument("value")

    lean_parser = subparsers.add_parser("lean", help="Show or edit lean.json (same shape as `aq config`)")
    lean_parser.set_defaults(func=cmd_lean)
    lean_subparsers = lean_parser.add_subparsers(dest="lean_command")

    lean_get_parser = lean_subparsers.add_parser("get", help="Print a lean.json value")
    lean_get_parser.add_argument("dotted_path")

    lean_keys_parser = lean_subparsers.add_parser("keys", help="List leaf key paths (optionally scoped to a prefix)")
    lean_keys_parser.add_argument("dotted_prefix", nargs="?", default=None)

    lean_set_parser = lean_subparsers.add_parser("set", help="Set a lean.json value (JSON-parsed, string fallback)")
    lean_set_parser.add_argument("dotted_path")
    lean_set_parser.add_argument("value")

    retrain_parser = subparsers.add_parser(
        "retrain", help="Thin dispatcher to python -m retraining.orchestrator <stage> ..."
    )
    retrain_parser.add_argument(
        "stage",
        choices=[
            "plan",
            "train",
            "train_topology",
            "train_gating",
            "train_multitask",
            "train_sequence",
            "validate",
            "backtest",
            "commit",
            "promote",
            "rollback",
            "status",
        ],
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

    fetch_parser = subparsers.add_parser(
        "fetch", help="Ad-hoc fetch of historical OHLCV from Yahoo Finance for a ticker not yet in config.json"
    )
    fetch_parser.add_argument(
        "asset_class", choices=list(ASSET_CLASSES), help="Asset class (picks the Lean data_path/market convention)"
    )
    fetch_parser.add_argument("--ticker", required=True, help="Internal ticker, e.g. AAPL or BTCUSD")
    fetch_parser.add_argument("--start", required=True, type=_iso_date, help="Start date, ISO 8601 YYYY-MM-DD")
    fetch_parser.add_argument("--end", required=True, type=_iso_date, help="End date, ISO 8601 YYYY-MM-DD")
    fetch_parser.add_argument(
        "--apply", action="store_true", help="Actually write the zip file and update config.json (default: dry run, report only)"
    )
    fetch_parser.add_argument(
        "--expiry", default=None, help="Contract expiry, YYYY-MM-DD (required for asset_class futures/options; requires IB, see 'aq ib status')"
    )
    fetch_parser.add_argument("--strike", type=float, default=None, help="Strike price (required for asset_class options)")
    fetch_parser.add_argument("--right", choices=["call", "put"], default=None, help="Option right (required for asset_class options)")
    fetch_parser.set_defaults(func=cmd_fetch)

    ib_parser = subparsers.add_parser("ib", help="Check Interactive Brokers configuration/connectivity")
    ib_subparsers = ib_parser.add_subparsers(dest="ib_command", required=True)
    ib_subparsers.add_parser("status", help="Report disabled / credentials-missing / reachable")
    ib_parser.set_defaults(func=cmd_ib)

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
