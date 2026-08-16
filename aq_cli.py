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
import copy
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
from risk.manual_override import (
    read_kill_switch_manual_override,
    read_manual_trade_lock_override,
    write_kill_switch_manual_override,
    write_manual_trade_lock_override,
)

IB_ASSET_CLASSES = ("futures", "options")

ROOT_DIR = Path(__file__).resolve().parent
CONFIG_PATH = ROOT_DIR / "config.json"
LEAN_JSON_PATH = ROOT_DIR / "lean.json"
WEBUI_DIR = ROOT_DIR / "webui"
README_PATH = ROOT_DIR / "README.md"
ML_DIR = ROOT_DIR / "ml"

PACKAGE_NAME = "aether-quant"
UPDATE_CACHE_PATH = Path.home() / ".aq" / "update_check.json"
UPDATE_CHECK_INTERVAL_SECONDS = 24 * 60 * 60
UPDATE_CHECK_TIMEOUT_SECONDS = 2

# `lean backtest .` resolves quantconnect/lean:latest by default when no
# --image is given - a MUTABLE tag, so Docker re-checks and re-pulls
# whatever layers changed on every single run, even against an already-
# fully-cached local image (confirmed directly: a ~42.5GB re-pull kicked
# off on this exact machine because Docker Hub's `latest` had moved to a
# newer build than what was cached). Pinned here to a specific numbered
# QuantConnect build tag instead (confirmed to exist on Docker Hub) so
# every clone of this repo - not just this machine - gets a byte-
# identical, one-time-download engine image that never silently re-pulls.
# To intentionally move to a newer Lean engine: pull the new tag by hand
# first (`docker pull quantconnect/lean:<new-tag>`), confirm it works,
# then bump this constant - never let it drift back to `latest`.
PINNED_LEAN_ENGINE_IMAGE = "quantconnect/lean:17900"
# Local derivative used by `aq backtest` by default. It is built once from
# PINNED_LEAN_ENGINE_IMAGE and installs the packages this project needs but
# the official image does not provide (redis, httpx - see requirements/
# lean-runtime.txt). Keeping them in the image avoids Lean CLI's Windows-host
# bind mount of a generated requirements.txt file, which fails on some
# Docker Desktop setups. Tag is DERIVED from PINNED_LEAN_ENGINE_IMAGE's own
# tag, never a second hardcoded copy - _ensure_local_lean_engine_image()'s
# cache check is a `docker image inspect` on this exact tag, so if the two
# constants could drift apart, bumping the pinned base without remembering
# to bump this one too would silently keep reusing a stale local image
# built from the old base forever.
LOCAL_LEAN_ENGINE_IMAGE = f"aether-quant-lean:{PINNED_LEAN_ENGINE_IMAGE.rsplit(':', 1)[-1]}"

_ANSI_ESCAPE_PATTERN = re.compile(r"\x1b\[[0-9;]*m")
_TEST_BADGE_MARKER_START = "<!-- AQ:TEST_BADGE_START -->"
_TEST_BADGE_MARKER_END = "<!-- AQ:TEST_BADGE_END -->"
_TEST_COUNT_MARKER_START = "<!-- AQ:TEST_COUNT_START -->"
_TEST_COUNT_MARKER_END = "<!-- AQ:TEST_COUNT_END -->"


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


def _ensure_local_lean_engine_image() -> bool:
    """Build the small project-specific LEAN image when it is not cached."""
    image_check = subprocess.run(
        ["docker", "image", "inspect", LOCAL_LEAN_ENGINE_IMAGE],
        cwd=str(ROOT_DIR),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if image_check.returncode == 0:
        return True

    dockerfile = ROOT_DIR / "Dockerfile.lean"
    if not dockerfile.is_file():
        print(f"error: missing local LEAN image definition: {dockerfile}", file=sys.stderr)
        return False

    print(
        f"Building {LOCAL_LEAN_ENGINE_IMAGE} from {PINNED_LEAN_ENGINE_IMAGE} "
        "(one-time setup; the large base image is reused)..."
    )
    return _run(
        [
            "docker",
            "build",
            "--file",
            str(dockerfile),
            "--tag",
            LOCAL_LEAN_ENGINE_IMAGE,
            "--build-arg",
            f"LEAN_BASE_IMAGE={PINNED_LEAN_ENGINE_IMAGE}",
            str(ROOT_DIR),
        ]
    ) == 0


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
    seed = getattr(args, "seed", None)
    ranking_objective = getattr(args, "ranking_objective", None)
    if (seed is not None or ranking_objective is not None) and not (args.multitask_only or args.sequence_only):
        print(
            "aq train: --seed/--ranking-objective only apply to --multitask-only/--sequence-only - ignored here.",
            file=sys.stderr,
        )
    # V5.1 Phase 4 (item 4) - same not-silently-ignored precedent as
    # --seed/--ranking-objective above.
    if (
        getattr(args, "include_multitask", False)
        or getattr(args, "include_sequence", False)
        or getattr(args, "metrics", None) is not None
    ) and not args.walk_forward:
        print(
            "aq train: --include-multitask/--include-sequence/--metrics only apply to --walk-forward - ignored here.",
            file=sys.stderr,
        )
    if args.gating_only:
        return _train_gating_only()
    if args.multitask_only:
        return _train_multitask_only(seed=seed, ranking_objective=ranking_objective)
    if args.sequence_only:
        return _train_sequence_only(seed=seed, ranking_objective=ranking_objective)
    if args.topology_only:
        return _train_topology_only()
    if args.strategy_selector_only:
        return _train_strategy_selector_only()
    if args.rl_sizing_only:
        return _train_rl_sizing_only()
    cmd = [sys.executable, "train.py"]
    # A fully bare `aq train` (no scope flag at all) is the only case that
    # chains gating/multitask/sequence training on top of train.py's own
    # baseline+experts run below - --dataset-only/--init-only/--experts-only/
    # --walk-forward all still mean exactly what they say and stop there.
    bare_run = not (args.dataset_only or args.init_only or args.experts_only or args.walk_forward)
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
        if getattr(args, "include_multitask", False):
            cmd.append("--include-multitask")
        if getattr(args, "include_sequence", False):
            cmd.append("--include-sequence")
        if getattr(args, "metrics", None) is not None:
            cmd += ["--metrics", args.metrics]

    returncode = _run(cmd)
    if returncode != 0 or not bare_run:
        return returncode

    # Each of these installs straight into active ml/ the same way its own
    # --gating-only/--multitask-only/--sequence-only flag does - a bare
    # `aq train` genuinely trains baseline + experts + gating + multitask +
    # sequence, not just the first two. Stops at the first failure rather
    # than silently continuing with a partially-updated active model.
    for stage_name, stage_fn in (
        ("gating", _train_gating_only),
        ("multitask", _train_multitask_only),
        ("sequence", _train_sequence_only),
    ):
        returncode = stage_fn()
        if returncode != 0:
            print(f"aq train: stopped after {stage_name} training failed (exit {returncode}).", file=sys.stderr)
            return returncode
    return 0


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


def _train_multitask_only(seed: int | None = None, ranking_objective: str | None = None) -> int:
    """`aq train --multitask-only`: trains the joint direction+magnitude+
    volatility model (train_multitask.py) and installs it straight into
    active ml/ - identical shape to _train_gating_only() above, including
    the throwaway version-id / manual promotion-simulation / "skipped must
    never look like failed" handling.

    seed/ranking_objective (V5.1 Phase 3, item 1) - passed straight
    through to train_multitask.py's own --seed/--ranking-objective flags
    when provided, the `aq`-level entry point for the seed-ensembling/
    ranking-objective-A/B workflow that previously required calling the
    script directly."""
    version_id = f"multitask-only-{uuid.uuid4()}"
    cmd = [sys.executable, "train_multitask.py", "--version-id", version_id]
    if seed is not None:
        cmd += ["--seed", str(seed)]
    if ranking_objective is not None:
        cmd += ["--ranking-objective", ranking_objective]
    returncode = _run(cmd)
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


def _train_sequence_only(seed: int | None = None, ranking_objective: str | None = None) -> int:
    """`aq train --sequence-only`: trains the Phase 2 causal-TCN sequence
    encoder (train_sequence.py) and installs it straight into active ml/ -
    identical shape to _train_multitask_only()/_train_gating_only() above.

    seed/ranking_objective - see _train_multitask_only()'s identical
    docstring."""
    version_id = f"sequence-only-{uuid.uuid4()}"
    cmd = [sys.executable, "train_sequence.py", "--version-id", version_id]
    if seed is not None:
        cmd += ["--seed", str(seed)]
    if ranking_objective is not None:
        cmd += ["--ranking-objective", ranking_objective]
    returncode = _run(cmd)
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


def _train_topology_only() -> int:
    """`aq train --topology-only`: trains the learned topology overlay
    (train_topology.py) and installs it straight into active ml/ -
    identical shape to _train_multitask_only()/_train_gating_only()/
    _train_sequence_only() above.

    Different data source and a real prerequisite the other three
    trainers don't have: train_topology.py fits over realized trading
    outcomes pulled from Postgres (AETHER_POSTGRES_DSN env var, read by
    train_topology.py itself - no DSN plumbing needed here), and needs
    at least phase_v2.topology_learning.training.min_training_events
    (default 500) usable events from a lookback_days (default 90) window.
    That data only accumulates from runs with the full stack (Postgres +
    the audit worker) up - on a fresh checkout, or before Postgres has
    been running long enough, this is expected to hit the "skipped"
    branch below, not the "artifacts written" one. development/
    Problems.md #56 has the full offset-scale story this trainer feeds."""
    version_id = f"topology-only-{uuid.uuid4()}"
    returncode = _run([sys.executable, "train_topology.py", "--version-id", version_id])
    if returncode != 0:
        return returncode

    version_dir = ROOT_DIR / "ml" / "versions" / version_id
    artifact_names = ("topology_model.json", "topology_feature_schema.json", "topology_training_metrics.json")
    if any(not (version_dir / name).exists() for name in artifact_names):
        print(
            "aq train --topology-only: train_topology.py exited 0 but skipped writing artifacts "
            "(fewer than min_training_events realized-outcome events in the lookback window - needs "
            "Postgres up and the audit worker running long enough to accumulate them) - active ml/ left "
            "unchanged.",
            file=sys.stderr,
        )
        return 0

    ml_dir = ROOT_DIR / "ml"
    for name in artifact_names:
        shutil.copy2(version_dir / name, ml_dir / name)
    print(f"aq train --topology-only: copied {', '.join(artifact_names)} into active ml/.")
    return 0


def _train_strategy_selector_only() -> int:
    """`aq train --strategy-selector-only`: trains the learned multi-leg
    strategy-selector model (train_strategy_selector.py, V4.7,
    development/Problems.md #29's own framing) and installs it straight
    into active ml/ - identical shape to _train_topology_only()/
    _train_multitask_only()/_train_gating_only()/_train_sequence_only()
    above.

    Different, and much harder to satisfy, prerequisite than any of the
    other four: train_strategy_selector.py fits over
    "option_strategy_outcome" experience events (Postgres,
    AETHER_POSTGRES_DSN env var), which only main.py::
    _emit_option_strategy_outcome_if_pending() can ever emit - and that
    only fires for a multi-leg OPTION position that was actually opened
    AND closed. Unlike train_topology.py (dormant only until enough
    Postgres VOLUME accumulates from an already-running system), this
    trainer has NO data source at all until real option positions
    actually trade - confirmed during scoping research that every options
    code path in this repo is still IB-unverified with zero option assets
    in the live universe. Expect the "skipped" branch below on every run
    in this environment, indefinitely - see train_strategy_selector.py's
    own module docstring for the full story."""
    version_id = f"strategy-selector-only-{uuid.uuid4()}"
    returncode = _run([sys.executable, "train_strategy_selector.py", "--version-id", version_id])
    if returncode != 0:
        return returncode

    version_dir = ROOT_DIR / "ml" / "versions" / version_id
    artifact_names = (
        "strategy_selector_model.json",
        "strategy_selector_feature_schema.json",
        "strategy_selector_training_metrics.json",
    )
    if any(not (version_dir / name).exists() for name in artifact_names):
        print(
            "aq train --strategy-selector-only: train_strategy_selector.py exited 0 but skipped writing "
            "artifacts (no option_strategy_outcome events yet - needs real option positions to have actually "
            "traded and closed) - active ml/ left unchanged.",
            file=sys.stderr,
        )
        return 0

    ml_dir = ROOT_DIR / "ml"
    for name in artifact_names:
        shutil.copy2(version_dir / name, ml_dir / name)
    print(f"aq train --strategy-selector-only: copied {', '.join(artifact_names)} into active ml/.")
    return 0


def _train_rl_sizing_only() -> int:
    """`aq train --rl-sizing-only`: trains the offline contextual-bandit
    sizing overlay (train_rl_sizing.py, development/Problems.md #71) and
    installs it straight into active ml/ - identical shape to
    _train_topology_only()/_train_strategy_selector_only() above.

    Different, but much more tractable, prerequisite than either of those
    two: train_rl_sizing.py reads ml/datasets/{validation,backtest}_dataset.csv
    - NOT Postgres, NOT real option trades - so this can run any time a
    normal `python train.py` has already produced a multitask model and
    the standard dataset files. Requires phase1.features.input_set to
    already include Component D's 3 alt-data feature names (a retrain
    with those in the schema) - see train_rl_sizing.py's own module
    docstring for the full honest framing (full-information contextual
    bandit, NOT off-policy RL) and risk/rl_sizing.py for the abandon
    criteria this feature should be judged against before ever being
    enabled by default."""
    version_id = f"rl-sizing-only-{uuid.uuid4()}"
    returncode = _run([sys.executable, "train_rl_sizing.py", "--version-id", version_id])
    if returncode != 0:
        return returncode

    version_dir = ROOT_DIR / "ml" / "versions" / version_id
    artifact_names = ("rl_sizing_model.json", "rl_sizing_feature_schema.json", "rl_sizing_training_metrics.json")
    if any(not (version_dir / name).exists() for name in artifact_names):
        print(
            "aq train --rl-sizing-only: train_rl_sizing.py exited 0 but skipped writing artifacts "
            "(fewer than min_training_rows usable rows, or the multitask model/dataset files are missing) - "
            "active ml/ left unchanged.",
            file=sys.stderr,
        )
        return 0

    ml_dir = ROOT_DIR / "ml"
    for name in artifact_names:
        shutil.copy2(version_dir / name, ml_dir / name)
    print(f"aq train --rl-sizing-only: copied {', '.join(artifact_names)} into active ml/.")
    return 0


def _update_readme_test_badge(passed: int, failed: int) -> None:
    """Atomically rewrites the shields.io test-count badge AND every
    AQ:TEST_COUNT-marked "N tests" prose mention (Test Suite section,
    Module Documentation table's tests/ row) in README.md, so neither ever
    drifts from the real collected-test total. Mirrors the equivalent
    mechanism in the sibling Aether-Vault project's `av test`. Never
    raises - a badge-update bug must never fail `aq test` itself."""
    total = passed + failed
    if total == 0:
        return  # nothing collected - leave the badge/count alone rather than zero them out
    if not README_PATH.is_file():
        return
    text = README_PATH.read_text(encoding="utf-8")

    if _TEST_BADGE_MARKER_START in text and _TEST_BADGE_MARKER_END in text:
        color = "brightgreen" if failed == 0 else "red"
        badge = (
            f'<img src="https://img.shields.io/badge/tests-{passed}%2F{total}%20passing-{color}'
            f'?style=flat-square&labelColor=1A1A1A" alt="{passed} of {total} tests passing">'
        )
        badge_pattern = re.compile(
            re.escape(_TEST_BADGE_MARKER_START) + r".*?" + re.escape(_TEST_BADGE_MARKER_END), re.DOTALL
        )
        text = badge_pattern.sub(f"{_TEST_BADGE_MARKER_START}{badge}{_TEST_BADGE_MARKER_END}", text, count=1)

    if _TEST_COUNT_MARKER_START in text and _TEST_COUNT_MARKER_END in text:
        count_pattern = re.compile(
            re.escape(_TEST_COUNT_MARKER_START) + r".*?" + re.escape(_TEST_COUNT_MARKER_END), re.DOTALL
        )
        text = count_pattern.sub(f"{_TEST_COUNT_MARKER_START}{total}{_TEST_COUNT_MARKER_END}", text)

    original_text = README_PATH.read_text(encoding="utf-8")
    if text == original_text:
        return

    tmp_path = README_PATH.with_suffix(README_PATH.suffix + ".tmp")
    tmp_path.write_text(text, encoding="utf-8")
    tmp_path.replace(README_PATH)
    print(f"Updated README.md test badge/count: {passed}/{total} passing")


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


# Subsystem -> tests/*.py filenames, used only when the user passes one or
# more --<subsystem> flags to filter the run. Not required to be exhaustive
# (the default, flag-less `aq test` just runs tests/ directly - marker-based
# exclusion, not this mapping, is what makes that complete) but kept
# reasonably complete so the flags are actually useful for "test every
# subsystem" one at a time. test_lean_backtest_ml_coverage.py is
# deliberately absent from every bucket - it's gated by the lean_backtest
# marker (see --lean/--full below), never by a subsystem flag.
#
# Hand-maintained, not derived from the filesystem - real drift found and
# fixed once already (~14 files, including a whole missing "audit" bucket,
# had silently fallen off every group). tests/test_aq_cli.py::
# test_subsystem_test_files_maps_every_real_test_file_to_exactly_one_bucket()
# now locks in "every real test file (except the one deliberate exclusion
# above) is in exactly one bucket" so a new test file missing from every
# bucket fails CI instead of quietly working only via the flag-less
# default run.
_SUBSYSTEM_TEST_FILES: dict[str, list[str]] = {
    "cli": [
        "test_aq_cli.py", "test_generate_backtest_report.py", "test_generate_evaluation_report.py",
        "test_lean_config_render.py", "test_dockerignore_secrets.py", "test_secret_scan.py",
        "test_profile_inference.py", "test_profile_subsystems.py", "test_lean_runtime_imports.py",
        "test_order_events_audit.py",
    ],
    "audit": [
        "test_hash_chain.py", "test_audit_queue.py", "test_postgres_audit.py",
        "test_audit_postgres_worker.py", "test_audit_status_export.py",
    ],
    "risk": [
        "test_risk_controls.py", "test_asset_class_router.py", "test_futures_risk.py",
        "test_forex_risk.py",
        "test_order_gate.py", "test_position_sizing.py", "test_backtest_gate.py",
        "test_validation_gate.py", "test_manual_override.py", "test_rl_sizing.py",
        # V5.1 Phase 6 (production safety) - risk/kill_switch.py,
        # execution/reconciliation.py (grouped here, not a dedicated
        # "execution" bucket, alongside every other production-safety
        # risk mechanism in this list).
        "test_kill_switch.py", "test_reconciliation.py",
    ],
    "portfolio": [
        "test_portfolio_book_construction.py", "test_options_strategy.py",
        "test_options_strategy_multileg.py", "test_options_arbitrage_detector.py",
        "test_options_margin_sizing.py",
        "test_options_greeks.py", "test_simulated_portfolio.py", "test_options_assignment_risk.py",
        # V5.1 Phase 1 (development/Problems.md #73) - portfolio/rank_signal.py.
        "test_rank_signal.py",
    ],
    "features": [
        "test_bond_features.py", "test_derivatives_macro_features.py", "test_macro_features.py",
        "test_technical_indicators.py", "test_train_bond_features.py",
        "test_train_derivatives_macro_features.py", "test_train_macro_features.py",
        "test_train_asset_class_context_features.py", "test_train_cross_sectional_features.py",
        "test_train_indicators.py", "test_alt_data_features.py", "test_train_alt_data_features.py",
        # V5.1 Phase 2 (item 8 / F2) - features/cross_asset_sensitivity.py.
        "test_cross_asset_sensitivity.py", "test_train_cross_asset_sensitivity.py",
    ],
    "data-pipeline": [
        "test_fetch.py", "test_ib_backfill.py", "test_fred_backfill.py", "test_yfinance_backfill.py",
        "test_dividend_backfill.py", "test_factor_file_backfill.py",
    ],
    "webui": [
        "test_neural_network_state.py", "test_assets_status.py", "test_status_export.py",
        "test_rank_ic_monitor.py", "test_observation_metrics.py", "test_strategy_catalog.py",
        "test_api_server.py",
    ],
    "ml": [
        "test_expert_models.py", "test_expert_datasets.py", "test_gating_network.py", "test_train_gating.py",
        "test_train_multitask.py", "test_train_multitask_architecture.py", "test_train_sequence.py",
        "test_train_sequence_architecture.py", "test_train_pipeline.py", "test_train_ranking_validation.py",
        "test_train_walk_forward_windows.py", "test_train_topology.py", "test_learned_topology.py",
        "test_exported_model.py", "test_market_topology.py", "test_market_regime.py",
        "test_market_analyzer.py", "test_market_liquidity.py",
        "test_train_strategy_selector.py", "test_strategy_selector_inference.py",
        "test_parallel_inference.py", "test_train_threshold_and_early_stop.py",
        "test_train_select_model_context_columns.py", "test_train_rl_sizing.py",
        # V5.1 Phase 2 (item 5 of the roadmap) - train.py::build_residual_rank_targets().
        "test_train_residual_rank_targets.py",
        # V5.1 Phase 3 (items 1, 10, 11) - cross-sectional batching, ranking
        # losses, optimizer/schedule/SWA/smoothing helpers.
        "test_train_cross_sectional_batching.py", "test_train_ranking_loss.py", "test_train_optimizer_and_swa.py",
        # V5.1 Phase 4 (item 4) - multi-model walk-forward subprocess/net-
        # performance-simulation helpers.
        "test_walk_forward_multimodel.py",
        # V5.2.8 (Problems.md #94) - train.py::compute_gate_friendliness_weight_by_date().
        "test_train_gate_friendliness.py",
    ],
    "retraining": [
        "test_retraining_artifacts.py", "test_retraining_orchestrator.py", "test_retraining_planning.py",
        "test_retraining_postgres_registry.py", "test_retraining_worker.py", "test_trigger_worker.py",
        "test_triggers.py", "test_vault_client.py", "test_vault_commands.py", "test_lean_backtest.py",
        "test_v2_pipeline_manifest.py",
        # V5.1 Phase 6 (production safety) - retraining/auto_rollback.py.
        "test_auto_rollback.py",
    ],
    "notifications": ["test_telegram_alerts.py", "test_telegram_client.py", "test_telegram_worker.py", "test_postgres_telegram.py"],
    "storage": ["test_postgres_triggers.py", "test_postgres_worker.py", "test_config_cache.py", "test_runtime_config_io.py", "test_experience_queue.py"],
    "live": [
        "test_live_credentials.py", "test_live_credentials_io.py", "test_paper_readiness.py",
        "test_paper_readiness_io.py", "test_paper_readiness_report.py", "test_paper_readiness_scheduler.py",
    ],
    "evaluation": [
        "test_rank_book_simulator.py", "test_book_neutrality.py", "test_cost_model.py",
        "test_model_predictions.py", "test_evaluation_state.py", "test_sector_map.py",
        # V5.1 Phase 5 (item 9) - evaluation/ablation.py.
        "test_ablation.py",
        # V5.1 (Problems.md) - evaluation/rank_signal_calibration.py.
        "test_rank_signal_calibration.py",
        # V5.2.6 (Problems.md) - evaluation/confidence_threshold_calibration.py.
        "test_confidence_threshold_calibration.py",
        # V5.2.8 (Problems.md #94) - evaluation/kill_switch_replay.py.
        "test_kill_switch_replay.py",
        # V5.3.1 (Problems.md #34/#96) - evaluation/limit_fill_simulator.py.
        "test_limit_fill_simulator.py",
    ],
}


def cmd_test(args: argparse.Namespace) -> int:
    """Runs pytest with live-streamed output (same UX as a plain
    subprocess.run), while also capturing it so the real pass/fail count can
    be parsed afterward and used to refresh README.md's test badge - mirrors
    the sibling Aether-Vault project's `av test` exactly.

    Default (no flags): excludes tests/test_lean_backtest_ml_coverage.py's
    lean_backtest-marked tests - a real `lean backtest .` run there takes
    over an hour wall-clock, and this repo's own .venv happens to have a
    real Lean CLI installed, so that file's skipif alone never actually
    skipped it. --lean/--full opts back in. --parallel adds pytest-xdist's
    -n auto (off by default - multiple workers each importing torch is a
    real OOM risk on memory-constrained dev machines). One or more
    --<subsystem> flags restrict the run to _SUBSYSTEM_TEST_FILES'
    filenames for those subsystems instead of the whole tree."""
    cmd = [sys.executable, "-m", "pytest", "--color=yes", "--durations=15"]

    subsystem_files: list[str] = []
    for name in _SUBSYSTEM_TEST_FILES:
        if getattr(args, name.replace("-", "_"), False):
            subsystem_files.extend(_SUBSYSTEM_TEST_FILES[name])
    is_filtered_run = bool(subsystem_files)

    if is_filtered_run:
        cmd.extend(f"tests/{name}" for name in dict.fromkeys(subsystem_files))
    else:
        cmd.append("tests/")

    if getattr(args, "lean", False) or getattr(args, "full", False):
        if is_filtered_run:
            cmd.append("tests/test_lean_backtest_ml_coverage.py")
    else:
        cmd.extend(["-m", "not lean_backtest"])

    if getattr(args, "parallel", False):
        cmd.extend(["-n", "auto"])

    exit_code, output = _run_captured(cmd)

    captured = _ANSI_ESCAPE_PATTERN.sub("", output)
    passed_match = re.search(r"(\d+) passed", captured)
    failed_match = re.search(r"(\d+) failed", captured)
    error_match = re.search(r"(\d+) error", captured)
    # Only the full, unfiltered default run's pass/fail count reflects the
    # whole suite - updating the badge from a --cli-only or --lean-only
    # partial run would make it silently report a subset as if it were
    # everything.
    if passed_match and not is_filtered_run:
        passed = int(passed_match.group(1))
        failed = (int(failed_match.group(1)) if failed_match else 0) + (int(error_match.group(1)) if error_match else 0)
        _update_readme_test_badge(passed, failed)

    return exit_code


def cmd_backtest(args: argparse.Namespace) -> int:
    lean_binary = _find_quantconnect_lean_binary()
    if lean_binary is None:
        print("error: QuantConnect Lean CLI not found (checked .venv and PATH).", file=sys.stderr)
        return 1
    # The default is a small local derivative of the pinned official image.
    # It contains redis in the image itself, so Lean CLI does not need to
    # create and Windows-bind-mount a generated requirements.txt file.
    # --image remains an escape hatch for deliberately selecting another
    # engine image without editing this file.
    if args.image:
        engine_image = args.image
    else:
        if not _ensure_local_lean_engine_image():
            return 1
        engine_image = LOCAL_LEAN_ENGINE_IMAGE
    lean_command = [lean_binary, "backtest", ".", "--image", engine_image]
    # Lean CLI creates config/startup files with tempfile.mkdtemp(). On some
    # Windows Docker Desktop installations those Python-created directories
    # are not readable by Docker, while ordinary host files are. Run through
    # the project wrapper so every generated temp directory receives
    # Docker-readable inherited permissions before the container is created.
    windows_wrapper = ROOT_DIR / "scripts" / "run_lean_cli_windows.py"
    if sys.platform == "win32" and windows_wrapper.is_file():
        lean_command = [sys.executable, str(windows_wrapper), *lean_command[1:]]
    exit_code = _run(lean_command)
    # Attempt the README update regardless of exit_code, NOT only on == 0.
    # On a resource-constrained machine Lean's Python-interpreter teardown
    # can exceed its own hardcoded 10-second shutdown-isolator budget and
    # make `lean backtest` return a NON-zero exit code even though the
    # backtest itself fully completed and wrote valid results - a cosmetic
    # "PythonInitializer.Shutdown() ... Operation timed out" error that
    # fires AFTER statistics are already saved (see development/Problems.md).
    # update_readme_from_latest_backtest() self-guards: it only ever picks a
    # backtest folder whose result JSON has BOTH non-empty statistics and a
    # non-empty equity curve, so calling it after a genuinely-failed run
    # (e.g. an init-timeout that produced no statistics) is a safe no-op.
    # Decoupling the README update from Lean's flaky shutdown-phase exit
    # code is the robust fix - the exit code is still returned to the caller.
    try:
        from generate_backtest_report import update_readme_from_latest_backtest

        if update_readme_from_latest_backtest():
            print("Updated README.md's Backtest Results section.")
    except Exception as error:  # noqa: BLE001 - must never fail the backtest command itself
        print(f"warning: failed to update README.md's backtest results ({error})", file=sys.stderr)
    # Also refreshes Other Metrics (Lean-vs-offline comparison) with this
    # backtest's fresh Sharpe, rather than leaving it stale until the next
    # `aq evaluate` run - same self-guarding, never-fail contract as above.
    _refresh_readme_evaluation_sections()
    if exit_code != 0:
        print(
            "note: `lean backtest` returned a non-zero exit code. If the run reached the end date and "
            "statistics were written, this is most likely the benign Python-shutdown timeout on a "
            "resource-constrained machine (development/Problems.md) - the README was still updated from "
            "the completed results above. Check the backtest log if unsure the run actually finished.",
            file=sys.stderr,
        )
    return exit_code


# One flag per scripts/profile_subsystems.py subsystem - same
# established loop-generated-flags convention as _SUBSYSTEM_TEST_FILES
# above (`aq test --cli --risk` etc.), applied to `aq profile` instead of
# `aq test`. Values aren't used (dispatch is by attribute presence, same
# as cmd_test()) - a plain tuple would do, kept as a dict of Nones so the
# iteration pattern below reads identically to _SUBSYSTEM_TEST_FILES's.
_PROFILE_SUBSYSTEM_FLAGS: dict[str, None] = {
    "regime": None, "topology": None, "topology-cached": None, "learned-topology": None, "liquidity": None,
    "gating": None, "analyzer": None, "indicators": None, "options": None,
}


def cmd_profile(args: argparse.Namespace) -> int:
    """Wraps scripts/profile_inference.py (default) - the cProfile+wall-
    clock harness for main.py's per-bar inference hot path (see
    development/Problems.md for what it found: weight-array/batched-stack
    caching, expert-loop batching, and _conv1d_causal vectorization,
    -89.2% total profiled cost) - or, when any --<subsystem> flag is set,
    scripts/profile_subsystems.py instead (regime/topology/topology-cached/
    liquidity/gating/analyzer/indicators/options - everything else main.py
    calls per bar that inference profiling never covered; --topology-cached
    exercises development/Problems.md#36's correlation-stability cache
    against slowly-drifting synthetic data, since --topology's fully
    independent per-iteration returns can never show that cache's
    benefit; --options exercises risk/asset_class_router.py::
    route_multi_leg_option_sizing() end-to-end, V4.9 Priority 7). Same
    subprocess-wrapper convention every other non-`trade-lock`/`fetch`
    command follows (_run(), not an in-process import).

    --batched/--no-gc/--bucket-report/--parallel/--pool-workers/
    --symbols-per-bar only have meaning for the inference path (no batched
    variant, GC-isolation/bucketing diagnostic, or process-pool benchmark
    exists for these pure subsystem functions) - combining any of them
    with a subsystem flag is a user error, rejected loudly rather than
    silently ignored. --parallel (V4.9 Priority 6) runs a real
    ProcessPoolExecutor benchmark of inference/parallel_inference.py's
    run_symbol_inference() against a sequential baseline, answering that
    module's own never-measured IPC/pickling break-even warning."""
    subsystem_flags = [name for name in _PROFILE_SUBSYSTEM_FLAGS if getattr(args, name.replace("-", "_"), False)]
    inference_only_flags = args.batched or args.no_gc or args.bucket_report or args.parallel
    if subsystem_flags and inference_only_flags:
        print(
            "error: --batched/--no-gc/--bucket-report/--parallel only apply to inference profiling, not --<subsystem> flags",
            file=sys.stderr,
        )
        return 1

    if subsystem_flags:
        cmd = [sys.executable, "scripts/profile_subsystems.py"]
        if args.iterations is not None:
            cmd.extend(["--iterations", str(args.iterations)])
        cmd.extend(["--sort", args.sort])
        cmd.extend(f"--{name}" for name in subsystem_flags)
        return _run(cmd)

    cmd = [sys.executable, "scripts/profile_inference.py"]
    if args.iterations is not None:
        cmd.extend(["--iterations", str(args.iterations)])
    cmd.extend(["--sort", args.sort])
    if args.batched:
        cmd.append("--batched")
    if args.no_gc:
        cmd.append("--no-gc")
    if args.bucket_report:
        cmd.append("--bucket-report")
    if args.parallel:
        cmd.append("--parallel")
    if args.pool_workers is not None:
        cmd.extend(["--pool-workers", str(args.pool_workers)])
    if args.symbols_per_bar is not None:
        cmd.extend(["--symbols-per-bar", str(args.symbols_per_bar)])
    return _run(cmd)


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
        # "engine" is the one consolidated build (aether-quant-engine) that
        # backs the app AND every worker below - see docker-compose.yml's
        # own comment on the `engine` service and requirements/README.md.
        services = [
            "redis",
            "postgres",
            "engine",
            "experience-worker",
            "audit-worker",
            "performance-trigger-worker",
            "retraining-worker",
            "telegram-worker",
        ]
        return _run(["docker", "compose", "up", "-d", *services])
    if args.lean:
        return _run(["docker", "compose", "--profile", "lean", "up", "-d"])
    return _run(["docker", "compose", "up", "-d", "redis", "postgres"])


def cmd_docker_build(_args: argparse.Namespace) -> int:
    return _run(["docker", "compose", "build", "engine"])


def cmd_render_lean_config(args: argparse.Namespace) -> int:
    """Render the gitignored lean.live.json from .env.live / AETHER_* env vars.
    The tracked lean.json stays all-empty; live/paper deploy uses the rendered
    file via `--lean-config`. See execution/lean_config_render.py."""
    from execution.lean_config_render import build_render_environment, write_rendered_config

    base = Path(args.base) if args.base else LEAN_JSON_PATH
    out = Path(args.out) if args.out else ROOT_DIR / "lean.live.json"
    env_file = Path(args.env_file) if args.env_file else ROOT_DIR / ".env.live"

    try:
        filled = write_rendered_config(base, out, build_render_environment(env_file=env_file))
    except FileNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    # Credential-load audit event (development/Problems.md #42) - field
    # NAMES only, matching the print statement below. A short-lived local
    # AuditQueue (this is a one-shot CLI invocation, not a long-running
    # process like main.py's) - never blocks/raises on a Redis hiccup.
    try:
        from audit import AuditQueue, CREDENTIAL_LOAD, build_audit_event

        config = json.loads(CONFIG_PATH.read_text(encoding="utf-8")) if CONFIG_PATH.exists() else {}
        audit_config = config.get("phase_v2", {}).get("audit_log", {})
        AuditQueue(
            enabled=bool(audit_config.get("enabled", True)),
            stream_name=str(audit_config.get("redis_stream", "aether:audit")),
        ).push(build_audit_event(CREDENTIAL_LOAD, {"loaded_fields": filled}, actor="cli"))
    except Exception:  # noqa: BLE001 - audit logging must never fail this command
        pass

    if filled:
        # Field NAMES only - never the secret values.
        print(f"Rendered {out} with {len(filled)} field(s): {', '.join(filled)}")
    else:
        print(
            f"Rendered {out}, but NO secret fields were populated - check that "
            f"{env_file} exists and its AETHER_* values are set."
        )
    print(f"Deploy against it with Lean's  --lean-config {out}")
    return 0


def cmd_secrets_check(_args: argparse.Namespace) -> int:
    """Fail (non-zero) if secrets are about to be committed: a populated
    secret field in the tracked lean.json, or a tracked real `.env` file.
    Backs .githooks/pre-commit. Pure detection lives in
    execution/secret_scan.py."""
    from execution.secret_scan import find_populated_secret_fields, is_tracked_env_secret

    problems: list[str] = []

    if LEAN_JSON_PATH.exists():
        try:
            lean_config = json.loads(LEAN_JSON_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            print(f"Error reading lean.json: {exc}", file=sys.stderr)
            return 1
        populated = find_populated_secret_fields(lean_config)
        if populated:
            problems.append(
                "lean.json has populated secret field(s) that must not be committed "
                f"(render them into gitignored lean.live.json instead): {', '.join(populated)}"
            )

    # Ask git which files are tracked; flag any real .env among them. Degrades
    # gracefully (skips this check) outside a git repo or without git on PATH.
    try:
        tracked = subprocess.run(
            ["git", "ls-files"], cwd=str(ROOT_DIR), capture_output=True, text=True
        )
        if tracked.returncode == 0:
            for path in tracked.stdout.splitlines():
                if is_tracked_env_secret(path):
                    problems.append(f"tracked secret file must not be committed: {path}")
    except (OSError, FileNotFoundError):
        pass

    if problems:
        print("aq secrets-check FAILED:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1

    print("aq secrets-check passed: no committed secrets detected.")
    return 0


def cmd_audit_log(args: argparse.Namespace) -> int:
    """Query the tamper-evident audit log (development/Problems.md #42) -
    order placement, credential loads, live-mode transitions. Requires
    AETHER_POSTGRES_DSN (same var every other Postgres-backed `aq` command
    uses) - the audit-worker service must have drained at least one batch
    from Redis into Postgres for anything to show up here (see
    docker-compose.yml's audit-worker service / `python -m audit.postgres_worker`)."""
    import psycopg

    from audit import fetch_all_events_ordered, fetch_recent_events, verify_chain

    dsn = os.environ.get("AETHER_POSTGRES_DSN", "")
    if not dsn:
        print("error: AETHER_POSTGRES_DSN is not set.", file=sys.stderr)
        return 1

    try:
        conn = psycopg.connect(dsn, autocommit=False)
    except Exception as exc:
        print(f"error: could not connect to Postgres: {exc}", file=sys.stderr)
        return 1

    try:
        if args.verify:
            rows = fetch_all_events_ordered(conn)
            valid, broken_index = verify_chain(rows)
            if not rows:
                print("aq audit-log --verify: table is empty — trivially valid.")
                return 0
            if valid:
                print(f"aq audit-log --verify: chain intact across {len(rows)} entries.")
                return 0
            broken_row = rows[broken_index]
            print(
                f"aq audit-log --verify: CHAIN BROKEN at entry {broken_index} "
                f"(event_id={broken_row['event_id']}, event_type={broken_row['event_type']}, "
                f"created_at={broken_row['created_at']}) — tampering or data loss detected.",
                file=sys.stderr,
            )
            return 1

        since = None
        if args.since:
            from datetime import datetime as _datetime, timezone as _timezone

            since = _datetime.fromisoformat(args.since).replace(tzinfo=_timezone.utc)
        rows = fetch_recent_events(conn, event_type=args.event_type, since=since, limit=args.limit)
        if not rows:
            print("aq audit-log: no matching entries.")
            return 0
        for row in rows:
            print(f"{row['created_at']}  {row['event_type']:<20} {row['actor']:<8} {json.dumps(row['payload'])}")
        return 0
    finally:
        conn.close()


def cmd_retrain(args: argparse.Namespace) -> int:
    return _run([sys.executable, "-m", "retraining.orchestrator", args.stage, *args.retrain_args])


# Phase 4.8 - whole-universe bulk-backfill scripts, each its own standalone
# argparse/__main__ module with a PLURAL filter (--tickers/--series nargs="*",
# --apply) - genuinely different from cmd_fetch()'s single-ticker/ad-hoc IB
# tool below, which does NOT wire to or overlap with any of these three.
# None of them was reachable via `aq` before this - purely a discoverability
# wrapper, zero new backfill logic (each script's own main()/argparse is
# unchanged and still works standalone via `python -m data_pipeline.<module>`).
_BACKFILL_MODULE_BY_TARGET: dict[str, str] = {
    "dividends": "data_pipeline.dividend_backfill",
    "fred": "data_pipeline.fred_backfill",
    "yfinance": "data_pipeline.yfinance_backfill",
}


def cmd_backfill(args: argparse.Namespace) -> int:
    return _run([sys.executable, "-m", _BACKFILL_MODULE_BY_TARGET[args.target], *args.backfill_args])


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


def _cmd_kill_switch_history(args: argparse.Namespace) -> int:
    """Queries the SAME tamper-evident audit log as `aq audit-log`
    (development/Problems.md #42), filtering for kill-switch trips. main.py's
    Phase 6 wiring pushes a trip as a LIVE_MODE_TRANSITION event with
    payload {"event": "kill_switch_tripped", ...} - LIVE_MODE_TRANSITION is
    reused rather than registering a new EVENT_TYPES entry (audit/redis_queue.py
    fixes that tuple; build_audit_event() raises ValueError on anything else)."""
    import psycopg

    from audit import LIVE_MODE_TRANSITION, fetch_recent_events

    dsn = os.environ.get("AETHER_POSTGRES_DSN", "")
    if not dsn:
        print("error: AETHER_POSTGRES_DSN is not set.", file=sys.stderr)
        return 1

    try:
        conn = psycopg.connect(dsn, autocommit=False)
    except Exception as exc:
        print(f"error: could not connect to Postgres: {exc}", file=sys.stderr)
        return 1

    try:
        rows = fetch_recent_events(conn, event_type=LIVE_MODE_TRANSITION, limit=args.limit)
        trip_rows = [row for row in rows if row["payload"].get("event") == "kill_switch_tripped"]
        if not trip_rows:
            print("aq kill-switch --history: no kill-switch trips recorded.")
            return 0
        for row in trip_rows:
            print(f"{row['created_at']}  {json.dumps(row['payload'])}")
        return 0
    finally:
        conn.close()


def cmd_kill_switch(args: argparse.Namespace) -> int:
    if args.arm:
        write_kill_switch_manual_override(True, CONFIG_PATH)
        print("Kill switch override: ARMED (forced evaluation active, even if phase_v2.risk.kill_switch.enabled is false).")
    elif args.disarm:
        write_kill_switch_manual_override(False, CONFIG_PATH)
        print("Kill switch override: DISARMED (forced off, even if phase_v2.risk.kill_switch.enabled is true).")
    elif args.auto:
        write_kill_switch_manual_override(None, CONFIG_PATH)
        print("Kill switch override: AUTO (defers to phase_v2.risk.kill_switch.enabled).")
    elif args.history:
        return _cmd_kill_switch_history(args)
    else:  # status
        override = read_kill_switch_manual_override(CONFIG_PATH)
        label = {True: "ARMED (forced on)", False: "DISARMED (forced off)", None: "AUTO (defers to config)"}[override]
        print(f"Kill switch override: {label}")
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
            if json_path == CONFIG_PATH and args.dotted_path == "phase_v2.inference_parallelism.enabled" and new_value:
                print(
                    "WARNING: phase_v2.inference_parallelism.enabled=true - development/Problems.md #65 "
                    "measured this ProcessPoolExecutor pool as dramatically slower than sequential on "
                    "Windows' spawn start method (never measured on Linux/fork). main.py will also log "
                    "this at startup on Windows if the pool actually starts.",
                    file=sys.stderr,
                )
            return 0

        if command == "preset":
            return _dispatch_config_preset_command(args, data, json_path)
    except ConfigPathError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    return 1


def _dispatch_config_preset_command(args: argparse.Namespace, data: dict, json_path: Path) -> int:
    """`aq config preset` (V5.1 Phase 1) - list/show/apply a named
    dotted-key-override block from phase_v2.presets. Reuses
    _get_config_value()/_set_config_value() so backup/type-coercion/old->new
    printing are IDENTICAL to a manual `aq config set` per key - a preset
    is just several `set` calls applied together, never a separate write
    path. Only registered under `config` (not `lean` - presets are a
    config.json-only concept)."""
    presets_root = data.get("phase_v2", {}).get("presets", {})
    preset_names = sorted(name for name in presets_root if name != "active")

    if args.preset_list:
        active = presets_root.get("active")
        for name in preset_names:
            print(f"{name}{' (active)' if name == active else ''}")
        return 0

    if args.preset_show:
        preset_values = presets_root.get(args.preset_show)
        if preset_values is None:
            print(f"error: no such preset {args.preset_show!r} - available: {preset_names}", file=sys.stderr)
            return 1
        print(json.dumps(preset_values, indent=2))
        return 0

    if args.preset_apply:
        preset_values = presets_root.get(args.preset_apply)
        if preset_values is None:
            print(f"error: no such preset {args.preset_apply!r} - available: {preset_names}", file=sys.stderr)
            return 1

        # Validate every dotted path resolves BEFORE writing anything -
        # apply the whole preset or none. A partial apply that failed
        # halfway through would leave config.json in a mixed state no
        # preset actually describes.
        for dotted_path in preset_values:
            _get_config_value(data, dotted_path)

        if args.preset_dry_run:
            for dotted_path, new_value in preset_values.items():
                old_value = _get_config_value(data, dotted_path)
                print(f"{dotted_path}: {old_value!r} -> {new_value!r} (dry run)")
            return 0

        shutil.copy2(json_path, json_path.with_suffix(".json.bak"))
        for dotted_path, new_value in preset_values.items():
            old_value, applied_value, type_changed = _set_config_value(data, dotted_path, json.dumps(new_value))
            print(f"{dotted_path}: {old_value!r} -> {applied_value!r}")
            if type_changed:
                print(f"WARNING: type changed for {dotted_path}", file=sys.stderr)
        if "active" in presets_root:
            _set_config_value(data, "phase_v2.presets.active", json.dumps(args.preset_apply))
        json_path.write_text(json.dumps(data, indent=4) + "\n", encoding="utf-8")
        return 0

    # No flag given - print the whole presets block, same "bare command
    # dumps everything" convention as `aq config` itself.
    print(json.dumps(presets_root, indent=2))
    return 0


def cmd_config(args: argparse.Namespace) -> int:
    return _dispatch_json_config_command(args, CONFIG_PATH, "config_command")


def cmd_lean(args: argparse.Namespace) -> int:
    return _dispatch_json_config_command(args, LEAN_JSON_PATH, "lean_command")

    return 1


def cmd_fetch(args: argparse.Namespace) -> int:
    ib = None
    fetch_fn = None
    extra_metadata = None
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

        family_ticker = args.family_ticker or args.ticker.upper()
        if args.asset_class == "futures":
            contract_spec = load_futures_contract_specs().get(args.ticker.upper(), {})
            fetch_fn = lambda symbol, start, end: fetch_future_historical_bars(  # noqa: E731
                ib, symbol, contract_spec, start, end, contract_month=args.contract_month
            )
            extra_metadata = {"family_ticker": family_ticker}
            if args.contract_month:
                extra_metadata["contract_month"] = args.contract_month
        else:
            fetch_fn = lambda symbol, start, end: fetch_option_historical_bars(  # noqa: E731
                ib, symbol, args.expiry, args.strike, args.right, start, end
            )
            extra_metadata = {
                "family_ticker": family_ticker,
                "strike": args.strike,
                "expiry": args.expiry,
                "right": args.right,
            }

    try:
        fetch_kwargs = {"fetch_fn": fetch_fn} if fetch_fn is not None else {}
        report = fetch_adhoc_asset(
            args.asset_class, args.ticker, args.start, args.end, apply=args.apply,
            extra_metadata=extra_metadata, **fetch_kwargs,
        )
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


def cmd_assets(_args: argparse.Namespace) -> int:
    """`aq assets status`: one command reporting full multi-asset-class
    readiness at a glance - IB, the futures_risk/options_risk feature
    flags, how many futures contract specs are loaded, how much of the
    FRED yield-curve cache is populated, and how many futures/options
    assets are actually configured in config.json's universe. Read-only
    reporting only - basic enable/disable of any of these already works
    today via the generic
    `aq config set phase_v2.{ib,futures_risk,options_risk}.enabled true|false`
    (_dispatch_json_config_command), same as cmd_ib's own "Enable with"
    hint.

    The actual report is built by monitoring/assets_status.py::
    build_assets_status() - shared with the webui's `/api/assets-status`
    endpoint so the readiness logic is defined exactly once."""
    from monitoring.assets_status import build_assets_status

    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    lean_config = json.loads(LEAN_JSON_PATH.read_text(encoding="utf-8"))
    report = build_assets_status(config, lean_config)

    print(f"IB: {report['ib_status']}")
    print(f"futures_risk.enabled: {report['futures_risk_enabled']}")
    print(f"options_risk.enabled: {report['options_risk_enabled']}")
    tickers = ", ".join(report["futures_contract_specs_tickers"]) or "none"
    print(f"Futures contract specs loaded: {report['futures_contract_specs_loaded']} ({tickers})")
    most_recent = report["fred_cache_most_recent_date"] or "never populated"
    print(f"FRED cache: {report['fred_cache_series_count']} series populated, most recent date: {most_recent}")
    print(f"Configured futures assets: {report['configured_futures_assets']}")
    print(f"Configured options assets: {report['configured_options_assets']}")
    # V5.1 Phase 2, Step 2.5 - development/Problems.md: derivatives macro
    # features are computed every dataset build, but deliberately left out
    # of phase1.features.input_set (constant 0.0 with no futures/options
    # contract subscribed - see build_dataset_manifest()'s
    # computed_but_unused_features list for the code-enforced version of
    # this same fact).
    derivatives_in_input_set = config.get("phase1", {}).get("features", {}).get("derivatives_in_input_set", False)
    status = "in input_set" if derivatives_in_input_set else "computed, NOT in input_set"
    print(
        "Derivatives macro features (futures_term_structure_slope, options_put_call_ratio, "
        f"options_implied_vol_skew): {status} - needs a futures/options contract subscribed "
        "(IB-gated) to carry real signal; flip phase1.features.derivatives_in_input_set "
        "once one is."
    )

    return 0


def _apply_preset_in_memory(config: dict, preset: dict) -> dict:
    """Applies a phase_v2.presets.<name> dotted-key overlay to an IN-MEMORY
    deep copy of `config` only - `aq evaluate --preset` must never write
    config.json (that is `aq config preset --apply`'s job, a separate
    command). Reuses _set_config_value()'s own dotted-path resolution -
    json.dumps() round-trips each already-typed preset value through the
    same string-coercion path `aq config set` uses, so both entry points
    share one implementation and can never silently disagree on how a
    dotted path resolves."""
    overlaid = copy.deepcopy(config)
    for dotted_path, value in preset.items():
        _set_config_value(overlaid, dotted_path, json.dumps(value))
    return overlaid


def _write_evaluation_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")


def _refresh_readme_evaluation_sections() -> None:
    """Best-effort call to generate_evaluation_report.py after any `aq
    evaluate` flag that could have changed what's on ml/evaluation/ or
    ml/versions/walk-forward-*/ - mirrors cmd_backtest()'s own "a report-
    generation bug must never fail the real command" contract. Lazily
    imported for the same reason as this function's pandas/torch imports
    above: every other `aq` subcommand's startup must stay unaffected."""
    try:
        from generate_evaluation_report import update_readme_evaluation_sections

        update_readme_evaluation_sections()
    except Exception as exc:  # noqa: BLE001 - report generation must never break `aq evaluate`
        print(f"warning: README evaluation-section refresh failed: {exc}", file=sys.stderr)


_EVALUATE_MODEL_ARTIFACTS = {
    "sequence": ("sequence_model.json", "sequence_feature_schema.json"),
    "multitask": ("multitask_model.json", "multitask_feature_schema.json"),
}


def cmd_evaluate(args: argparse.Namespace) -> int:
    """`aq evaluate`: offline, cost-aware evaluation of the cross-sectional
    rank book (V5.1 Phase 0, development/Problems.md) - turns "how good is
    this rank prediction" into "what would this have earned net of fees",
    the question nothing else in this codebase answers
    (train.py::compute_strategy_metrics() simulates a long-only
    1-day-direction strategy gross of costs, not the rank book, not net of
    cost). Runs every dataset row through inference/exported_model.py (the
    SAME torch-free interpreter main.py's live decision path uses) and
    evaluation/rank_book_simulator.py's simulate_rank_book() (which itself
    reuses portfolio/book_construction.py's build_rank_based_book() and
    portfolio/book_neutrality.py's apply_book_neutrality()) - so every
    number this prints is the offline mirror of live behavior, not a
    separately re-derived approximation.

    Heavy imports (pandas/numpy/evaluation/inference) are deliberately
    LAZY, inside this function body, not at module top - the same
    convention cmd_assets() already follows for monitoring.assets_status -
    so every other `aq` subcommand's startup stays exactly as fast as
    before this command existed.
    """
    import pandas as pd

    from evaluation import capacity_curve, predict_head, simulate_rank_book, stress_test_costs
    from features import load_sector_mapping

    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))

    if getattr(args, "preset", None):
        presets = config.get("phase_v2", {}).get("presets", {})
        preset = presets.get(args.preset)
        if preset is None:
            available = sorted(name for name in presets if name != "active")
            print(f"error: unknown preset {args.preset!r} - available: {available or 'none configured yet'}", file=sys.stderr)
            return 1
        config = _apply_preset_in_memory(config, preset)

    # V5.1 Phase 4 (item 4) - `aq evaluate --walk-forward-summary` reads an
    # already-written ml/versions/walk-forward-*/walk_forward_summary.json
    # (train.py::_run_walk_forward()'s output) rather than running anything
    # itself - a completely separate, lightweight code path from every
    # other --rank-book/--capacity/--stress/--calibrate-edge flag below,
    # so it returns early before any of that dataset/model loading.
    if getattr(args, "walk_forward_summary", False):
        versions_dir = ML_DIR / "versions"
        run_id = getattr(args, "run_id", None)
        if run_id:
            summary_path = versions_dir / run_id / "walk_forward_summary.json"
        else:
            candidates = sorted(versions_dir.glob("walk-forward-*/walk_forward_summary.json"), key=lambda p: p.stat().st_mtime)
            summary_path = candidates[-1] if candidates else None
        if summary_path is None or not summary_path.exists():
            print("error: no walk-forward summary found - run `aq train --walk-forward` first.", file=sys.stderr)
            return 1
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        if args.json:
            print(json.dumps(summary, indent=2))
        else:
            print(f"Walk-forward summary ({summary_path.parent.name}): {summary.get('num_windows', 0)} windows")
            for name, stats in (summary.get("summary_by_metric") or {}).items():
                bootstrap = stats.get("cross_window_bootstrap", {})
                print(
                    f"  {name}: mean={bootstrap.get('mean_ic', 0.0):.4f} "
                    f"95% CI=[{bootstrap.get('lower_bound', 0.0):.4f}, {bootstrap.get('upper_bound', 0.0):.4f}]"
                )
            for name, stability in (summary.get("stability_by_metric") or {}).items():
                status = "stable" if stability.get("stable") else "UNSTABLE"
                print(
                    f"  {name} stability: {status} "
                    f"(sign_flip_fraction={stability.get('sign_flip_fraction', 0.0):.2f}, "
                    f"num_windows={stability.get('num_windows', 0)})"
                )
            net_performance_windows = summary.get("net_performance_by_window") or []
            if net_performance_windows:
                print(f"  net_performance: {len(net_performance_windows)} window(s) with a simulated book")
        _refresh_readme_evaluation_sections()
        return 0

    # V5.2.2 (development/Problems.md) - `aq evaluate --reconcile-book-history`
    # compares a real Lean backtest's actual per-date book selections
    # (logged via phase_v2.diagnostics.book_history, see main.py's write
    # site) against a fresh offline re-derivation of the same raw scores -
    # true ground truth instead of more indirect offline-vs-live hypothesis
    # testing. Early-return, same precedent as --walk-forward-summary above:
    # needs its own UNFILTERED-by-split dataset load, because a recorded
    # date's required lookback context can reach into rows from a different
    # split boundary (see select_context_date_range()'s own docstring for
    # why naively reusing the split-filtered dataset below would be wrong).
    if getattr(args, "reconcile_book_history", False):
        from evaluation import (
            compute_blended_raw_scores,
            reconcile_book_history_date,
            replay_book_history_reconciliation,
            segment_logged_records_by_run,
            select_context_date_range,
            summarize_book_history_reconciliation,
            summarize_book_member_diversion,
            summarize_universe_presence_by_symbol,
            summarize_universe_snapshot_by_security_type,
        )
        from portfolio.rank_signal import resolve_rank_signal_policy

        book_history_path_arg = getattr(args, "book_history_path", None)
        diagnostics_config = config.get("phase_v2", {}).get("diagnostics", {}).get("book_history", {})
        book_history_path = (
            Path(book_history_path_arg)
            if book_history_path_arg
            else ROOT_DIR / diagnostics_config.get("output_path", "visualization/book_history.jsonl")
        )
        if not book_history_path.exists():
            print(
                f"error: {book_history_path} not found - run a backtest with "
                "phase_v2.diagnostics.book_history.enabled=true first.",
                file=sys.stderr,
            )
            return 1

        logged_records: list[dict] = []
        with open(book_history_path, "r", encoding="utf-8") as book_history_file:
            for line_number, raw_line in enumerate(book_history_file, start=1):
                stripped_line = raw_line.strip()
                if not stripped_line:
                    continue
                try:
                    logged_records.append(json.loads(stripped_line))
                except json.JSONDecodeError as error:
                    print(
                        f"warning: skipping malformed line {line_number} in {book_history_path}: {error}",
                        file=sys.stderr,
                    )

        if not logged_records:
            print(f"error: {book_history_path} contains no usable records.", file=sys.stderr)
            return 1

        # V5.3.2 (development/Problems.md #91/#97/#99) - book_history.jsonl
        # is a cumulative, NEVER-rotated log: every real backtest run's
        # records are appended to the same file forever. Reconciling
        # against it unsegmented (the pre-V5.3.2 behavior) silently merges
        # unrelated runs together - confirmed against the real file: 160 of
        # 174 unique dates recur across more than one run, one date in as
        # many as 8 - and a --replay-hysteresis walk carries held
        # allocations across a real run boundary as if it were one
        # continuous backtest. Segment FIRST; default to the MOST RECENT
        # run only, never a silent cross-run merge.
        run_segments = segment_logged_records_by_run(logged_records)
        if not run_segments:
            print(f"error: {book_history_path} contains no dated records.", file=sys.stderr)
            return 1

        reconcile_all_runs = bool(getattr(args, "reconcile_all_runs", False))
        reconcile_run_index_arg = getattr(args, "reconcile_run_index", None)
        requested_indices = (
            list(range(len(run_segments)))
            if reconcile_all_runs
            else [reconcile_run_index_arg if reconcile_run_index_arg is not None else -1]
        )
        selected_run_indices: list[int] = []
        for raw_index in requested_indices:
            normalized_index = raw_index if raw_index >= 0 else raw_index + len(run_segments)
            if not (0 <= normalized_index < len(run_segments)):
                print(
                    f"error: --reconcile-run-index {raw_index} out of range - {len(run_segments)} run(s) "
                    f"detected in {book_history_path}.", file=sys.stderr,
                )
                return 1
            selected_run_indices.append(normalized_index)

        run_metadata_by_index: dict[int, dict] = {}
        for i, run_records in enumerate(run_segments):
            run_dates = [record["date"] for record in run_records if record.get("date")]
            run_metadata_by_index[i] = {
                "num_runs_detected": len(run_segments),
                "selected_run_index": i,
                "start_date": run_dates[0] if run_dates else None,
                "end_date": run_dates[-1] if run_dates else None,
                "num_records": len(run_records),
            }

        recon_dataset_path = ML_DIR / "datasets" / "full_dataset.csv"
        if not recon_dataset_path.exists():
            print(f"error: {recon_dataset_path} not found - run `aq train --dataset-only` first.", file=sys.stderr)
            return 1
        full_dataset = pd.read_csv(recon_dataset_path)
        if "training_eligible" in full_dataset.columns:
            full_dataset = full_dataset[full_dataset["training_eligible"]].reset_index(drop=True)

        sequence_window_default = config.get("phase_v2", {}).get("sequence_model", {}).get("window_size", 30)
        rank_signal_config = config.get("phase_v2", {}).get("rank_signal", {})
        training_metrics_by_model: dict[str, dict | None] = {}
        for model_name, metrics_filename in (
            ("sequence", "sequence_training_metrics.json"),
            ("multitask", "multitask_training_metrics.json"),
        ):
            metrics_path = ML_DIR / metrics_filename
            training_metrics_by_model[model_name] = (
                json.loads(metrics_path.read_text(encoding="utf-8")) if metrics_path.exists() else None
            )
        policy = resolve_rank_signal_policy(training_metrics_by_model, config)
        active_heads = [head_name for head_name, weight in policy["heads"].items() if weight > 0.0]

        # V5.3.2 (development/Problems.md #91/#97/#99) - the SAME symbol
        # order main.py's self.symbols uses (config.json's
        # phase1.universe.assets, in file order) - cross_sectional_rank_scores()/
        # _select_book_group() are both Python-stable sorts keyed only on
        # score, so an exact tie between two symbols resolves by dict
        # insertion order. Live builds its raw-scores dict in self.symbols
        # order; this reconciliation tool previously built it from a pandas
        # groupby (dataset row order) - a different, uncorrelated order -
        # so a tied pair near a top/bottom-N boundary could pick a
        # different winner offline than live with byte-identical scores.
        # Re-inserting in this canonical order before it ever reaches
        # cross_sectional_rank_scores() fixes that, with zero changes to
        # the live decision path itself.
        canonical_symbol_order = [
            str(asset.get("ticker")) for asset in config.get("phase1", {}).get("universe", {}).get("assets", [])
        ]

        book_config = config.get("phase_v2", {}).get("portfolio_book", {})
        strategy_mode = config.get("phase5", {}).get("backtest", {}).get("strategy_mode", "long_flat")
        book_top_n = int(book_config.get("top_n", 6))
        book_bottom_n = int(book_config.get("bottom_n", 6)) if strategy_mode == "long_short" else 0
        # V5.2.3 (development/Problems.md #91) - --replay-hysteresis
        # switches from independently reconciling each date (the
        # V5.2.2 default - can't tell a real divergence apart from
        # hysteresis correctly holding an incumbent) to a walk-forward
        # replay of offline's OWN selection history, carrying hysteresis
        # forward the same way main.py's live book does.
        replay_hysteresis = bool(getattr(args, "replay_hysteresis", False))
        hysteresis_rank_margin = float(book_config.get("hysteresis_rank_margin", 0.0))

        def _reconcile_one_run(run_records: list[dict]) -> dict:
            # V5.3.2: each run gets its OWN context date range/predictions -
            # previously computed once over the entire cumulative file's
            # date span even when only one small run was being reconciled.
            recorded_dates = sorted({record["date"] for record in run_records if record.get("date")})
            logged_records_by_date = {record["date"]: record for record in run_records if record.get("date")}

            recon_min_date, recon_max_date = select_context_date_range(
                full_dataset, recorded_dates, window_size=int(sequence_window_default)
            )
            context_dataset = full_dataset[
                (full_dataset["date"] >= recon_min_date) & (full_dataset["date"] <= recon_max_date)
            ].reset_index(drop=True)

            predictions_by_model_head: dict[str, dict[str, object]] = {}
            for model_kind_for_head in policy["model_priority"]:
                recon_model_filename, recon_schema_filename = _EVALUATE_MODEL_ARTIFACTS[model_kind_for_head]
                recon_model_path = ML_DIR / recon_model_filename
                recon_schema_path = ML_DIR / recon_schema_filename
                if not recon_model_path.exists() or not recon_schema_path.exists():
                    continue  # best-effort - same convention as --calibrate-book-spread above
                recon_model_export = json.loads(recon_model_path.read_text(encoding="utf-8"))
                recon_feature_schema = json.loads(recon_schema_path.read_text(encoding="utf-8"))
                recon_feature_names = recon_feature_schema["model_input_names"]
                head_predictions: dict[str, object] = {}
                for head_name in active_heads:
                    head_predictions[head_name] = predict_head(
                        context_dataset, recon_model_export, recon_feature_names, head_name,
                        model_kind=model_kind_for_head,
                        sequence_feature_schema=recon_feature_schema if model_kind_for_head == "sequence" else None,
                        configured_window_size=int(sequence_window_default),
                    )
                predictions_by_model_head[model_kind_for_head] = head_predictions

            context_dataset["raw_blended_score"] = compute_blended_raw_scores(
                context_dataset, predictions_by_model_head, policy
            )

            recorded_subset = context_dataset[context_dataset["date"].isin(recorded_dates)]
            raw_scores_by_date: dict[str, dict[str, float]] = {}
            for recon_date, group in recorded_subset.groupby("date", sort=True):
                if recon_date not in logged_records_by_date:
                    continue
                scores_lookup = {
                    str(ticker): float(score)
                    for ticker, score in zip(group["ticker"], group["raw_blended_score"])
                    if score is not None and not (isinstance(score, float) and pd.isna(score))
                }
                ordered_scores = {
                    ticker: scores_lookup[ticker] for ticker in canonical_symbol_order if ticker in scores_lookup
                }
                ordered_scores.update({t: s for t, s in scores_lookup.items() if t not in ordered_scores})
                raw_scores_by_date[recon_date] = ordered_scores

            if replay_hysteresis:
                ordered_logged_records = [
                    logged_records_by_date[d] for d in recorded_dates if d in raw_scores_by_date
                ]
                per_date_results = replay_book_history_reconciliation(
                    ordered_logged_records, raw_scores_by_date,
                    top_n=book_top_n, bottom_n=book_bottom_n, hysteresis_rank_margin=hysteresis_rank_margin,
                )
            else:
                per_date_results = [
                    reconcile_book_history_date(
                        logged_records_by_date[recon_date], raw_scores_by_symbol,
                        top_n=book_top_n, bottom_n=book_bottom_n,
                    )
                    for recon_date, raw_scores_by_symbol in raw_scores_by_date.items()
                ]

            summary = summarize_book_history_reconciliation(per_date_results)
            # Cheap and always attempted (pure, reads straight off the log's
            # own "universe" keys - no re-inference) - degrades to
            # num_dates_with_universe_data=0 for a log written without
            # include_full_universe, never raises. V5.3.2: computed over
            # this RUN's own records only, not the whole cumulative file.
            universe_summary = summarize_universe_snapshot_by_security_type(run_records)
            # V5.2.6 (development/Problems.md) - same "cheap, always attempted,
            # degrades to zeros" contract as universe_summary above - reads
            # straight off the log's own optional "book_member_decisions" key.
            diversion_summary = summarize_book_member_diversion(run_records)
            # V5.3.1 (development/Problems.md #91/#97) - summarize_universe_presence_by_symbol()
            # does its own internal run-segmentation too, but since run_records
            # is already a single run here, it always reports exactly one.
            universe_presence_summary = summarize_universe_presence_by_symbol(run_records)
            return {
                "mode": "replay_hysteresis" if replay_hysteresis else "independent",
                "per_date": per_date_results,
                "summary": summary,
                "universe_summary": universe_summary,
                "diversion_summary": diversion_summary,
                "universe_presence_summary": universe_presence_summary,
            }

        if reconcile_all_runs:
            all_runs_payloads = []
            for i in selected_run_indices:
                run_payload = _reconcile_one_run(run_segments[i])
                run_payload["run_metadata"] = run_metadata_by_index[i]
                all_runs_payloads.append(run_payload)
            # Top-level default keys mirror the most-recent run (last in
            # selected_run_indices, since run_segments is chronological) -
            # --reconcile-all-runs is additive on top of the normal default
            # output, never a replacement for it.
            payload = dict(all_runs_payloads[-1])
            payload["all_runs"] = all_runs_payloads
        else:
            selected_index = selected_run_indices[0]
            payload = _reconcile_one_run(run_segments[selected_index])
            payload["run_metadata"] = run_metadata_by_index[selected_index]

        _write_evaluation_json(ML_DIR / "evaluation" / "book_history_reconciliation.json", payload)

        if args.json:
            print(json.dumps(payload, indent=2, default=str))
        else:
            def _print_run_result(run_payload: dict, label: str) -> None:
                run_summary = run_payload["summary"]
                run_universe_summary = run_payload["universe_summary"]
                run_diversion_summary = run_payload["diversion_summary"]
                run_universe_presence_summary = run_payload["universe_presence_summary"]
                run_meta = run_payload["run_metadata"]
                print(f"{label}{run_meta['start_date']}..{run_meta['end_date']}, {run_summary['num_dates']} dates:")
                print(
                    f"  exact_match={run_summary['num_dates_exact_match']}/{run_summary['num_dates']}  "
                    f"mean_overlap_fraction={run_summary['mean_overlap_fraction']}"
                )
                print(
                    f"  mean_raw_score_delta_abs={run_summary['mean_raw_score_delta_abs']}  "
                    f"mean_weight_delta_abs={run_summary['mean_weight_delta_abs']} "
                    f"({run_summary['num_dates_with_weight_logged']}/{run_summary['num_dates']} dates had a "
                    "logged weight)"
                )
                print(
                    f"  symbols_only_logged_total={run_summary['num_symbols_only_logged_total']}  "
                    f"symbols_only_offline_total={run_summary['num_symbols_only_offline_total']}"
                )
                if run_universe_summary["num_dates_with_universe_data"] > 0:
                    print(
                        f"  Universe snapshot ({run_universe_summary['num_dates_with_universe_data']}/"
                        f"{run_summary['num_dates']} dates carry full-universe data):"
                    )
                    for security_type, stats in sorted(run_universe_summary["by_security_type"].items()):
                        print(
                            f"    {security_type}: mean_raw_rank_score={stats['mean_raw_rank_score']}  "
                            f"feature_ready_rate={stats['feature_ready_rate']}  "
                            f"trading_eligible_rate={stats['trading_eligible_rate']} "
                            f"(n={stats['num_symbol_dates']})"
                        )
                if run_diversion_summary["num_records_with_decisions"] > 0:
                    print(
                        f"  Book-member diversion ({run_diversion_summary['num_records_with_decisions']}/"
                        f"{run_summary['num_dates']} dates carry decision data, "
                        f"{run_diversion_summary['total_book_member_dates']} book-member-dates total):"
                    )
                    for action, count in sorted(
                        run_diversion_summary["action_counts"].items(), key=lambda item: -item[1]
                    ):
                        print(f"    action={action}: {count}")
                    for reason, count in sorted(
                        run_diversion_summary["reason_counts"].items(), key=lambda item: -item[1]
                    ):
                        print(f"    reason={reason}: {count}")
                if run_universe_presence_summary["num_runs_detected"] > 0:
                    top_absent = sorted(
                        run_universe_presence_summary["runs"][0]["absence_rate_by_symbol"].items(),
                        key=lambda item: -item[1],
                    )[:10]
                    for symbol, absence_rate in top_absent:
                        if absence_rate > 0:
                            print(f"    {symbol}: absent from universe on {absence_rate:.1%} of this run's dates")

            print(
                f"Book-history reconciliation ({book_history_path}): "
                f"{payload['run_metadata']['num_runs_detected']} run(s) detected total "
                "(cumulative, never-rotated log)."
            )
            if replay_hysteresis:
                print(
                    "  NOTE: this reconciliation REPLAYS hysteresis (--replay-hysteresis) - offline's own "
                    "held allocations are carried forward date-by-date, the same way main.py's live book "
                    "does, WITHIN each run only (V5.3.2: never across a run boundary). The first reconciled "
                    "date of each run still starts from a COLD (empty) held-allocations state regardless of "
                    "the book's true earlier history, so early dates may show a colder-start mismatch than "
                    "mid-series dates."
                )
            else:
                print(
                    "  NOTE: this reconciliation replays NO hysteresis (previous_allocations=None) - a "
                    "mismatch can mean either a real divergence OR the live book correctly holding an "
                    "incumbent that day's natural ranking alone wouldn't pick. Read per-date role_mismatches "
                    "before concluding anything is actually wrong. Pass --replay-hysteresis for the "
                    "hysteresis-aware alternative."
                )
            if reconcile_all_runs:
                num_runs = len(payload["all_runs"])
                for position, run_payload in enumerate(payload["all_runs"]):
                    _print_run_result(run_payload, f"Run {position + 1}/{num_runs} (")
            else:
                _print_run_result(payload, "Reconciled run (")

        _refresh_readme_evaluation_sections()
        return 0

    ranking_config = config.get("phase1", {}).get("target", {}).get("ranking", {})
    net_perf_config = ranking_config.get("net_performance", {})
    if not net_perf_config:
        print("error: phase1.target.ranking.net_performance is not configured.", file=sys.stderr)
        return 1

    dataset_path = ML_DIR / "datasets" / "full_dataset.csv"
    if not dataset_path.exists():
        print(f"error: {dataset_path} not found - run `aq train --dataset-only` first.", file=sys.stderr)
        return 1

    model_kind = args.model or "sequence"
    head = args.head or "rank_20d"
    split = args.split or "backtest"

    model_filename, schema_filename = _EVALUATE_MODEL_ARTIFACTS[model_kind]
    model_path = ML_DIR / model_filename
    schema_path = ML_DIR / schema_filename
    if not model_path.exists() or not schema_path.exists():
        print(f"error: {model_path} or {schema_path} not found - run `aq train` first.", file=sys.stderr)
        return 1

    model_export = json.loads(model_path.read_text(encoding="utf-8"))
    feature_schema = json.loads(schema_path.read_text(encoding="utf-8"))
    feature_names = feature_schema["model_input_names"]

    dataset = pd.read_csv(dataset_path)
    if "training_eligible" in dataset.columns:
        dataset = dataset[dataset["training_eligible"]].reset_index(drop=True)
    if split != "all":
        dataset = dataset[dataset["split"] == split].reset_index(drop=True)
    if dataset.empty:
        print(f"error: no rows for split={split!r} after filtering - check `aq train` has run for this window.", file=sys.stderr)
        return 1

    sequence_window_default = config.get("phase_v2", {}).get("sequence_model", {}).get("window_size", 30)
    predictions = predict_head(
        dataset, model_export, feature_names, head,
        model_kind=model_kind,
        sequence_feature_schema=feature_schema if model_kind == "sequence" else None,
        configured_window_size=int(sequence_window_default),
    )
    dataset = dataset.copy()
    dataset["predicted_head"] = predictions

    sector_by_ticker = load_sector_mapping(config)
    base_kwargs = dict(
        prediction_column="predicted_head",
        forward_return_column="target_return_1d",
        ticker_column="ticker",
        date_column="date",
        top_n=int(net_perf_config.get("top_n", 6)),
        bottom_n=int(net_perf_config.get("bottom_n", 6)),
        rebalance_every_bars=int(net_perf_config.get("rebalance_every_bars", 10)),
        cost_bps_per_side=float(net_perf_config.get("cost_bps_per_side", 5.0)),
        commission_bps=float(net_perf_config.get("commission_bps", 1.0)),
        gross_exposure=float(net_perf_config.get("gross_exposure", 1.0)),
        dollar_neutral=bool(net_perf_config.get("dollar_neutral", True)),
        sector_neutral=bool(net_perf_config.get("sector_neutral", True)),
        sector_by_ticker=sector_by_ticker,
        hysteresis_rank_margin=float(net_perf_config.get("hysteresis_rank_margin", 0.0)),
        max_weight_per_name=float(net_perf_config.get("max_weight_per_name", 0.12)),
        min_universe_size=int(ranking_config.get("min_universe_size", 20)),
        # V5.2.1 (development/Problems.md) - both no-op by default (0/0.0/0.0),
        # matching simulate_rank_book()'s own defaults exactly.
        entry_lag_bars=int(net_perf_config.get("entry_lag_bars", 0)),
        min_commission_usd=float(net_perf_config.get("min_commission_usd", 0.0)),
        assumed_portfolio_value_usd=float(net_perf_config.get("assumed_portfolio_value_usd", 0.0)),
    )

    run_rank_book = bool(args.rank_book or args.all)
    run_capacity = bool(args.capacity or args.all)
    run_stress = bool(args.stress or args.all)
    run_calibrate = bool(args.calibrate_edge or args.all)
    # V5.1 Phase 5 (item 9) - deliberately NOT bundled into --all (matching
    # the plan's own scoping: --all is rank-book/capacity/stress/calibrate-
    # edge only) - ablation is a heavier, opt-in-only report.
    run_ablation_flag = bool(getattr(args, "ablation", False))
    # V5.1 (Problems.md) - also deliberately NOT bundled into --all, same
    # reasoning as --ablation: a heavier, two-model, opt-in-only report.
    run_calibrate_book_spread = bool(getattr(args, "calibrate_book_spread", False))
    # V5.2.6 (development/Problems.md) - same reasoning as
    # run_calibrate_book_spread immediately above: a heavier, opt-in-only
    # report, not bundled into --all.
    run_calibrate_confidence_threshold = bool(getattr(args, "calibrate_confidence_threshold", False))
    # V5.2.8 (development/Problems.md #94) - same reasoning as --ablation/
    # --calibrate-book-spread above: a heavier, investigation-only report,
    # not bundled into --all.
    run_replay_kill_switch = bool(getattr(args, "replay_kill_switch", False))
    # V5.3.1 (development/Problems.md #34/#96) - same reasoning as
    # --replay-kill-switch above: a heavier, investigation-only report,
    # not bundled into --all.
    run_simulate_limit_fills = bool(getattr(args, "simulate_limit_fills", False))
    # Bare `aq evaluate` with no flags at all defaults to --rank-book - the
    # single most useful number ("is the fee drag fixed"), matching every
    # other `aq` command's "sane default when no scope flag is given"
    # convention (e.g. `aq test` with no subsystem flags runs everything).
    # Every opt-in-only flag (not just the --all-bundled ones) must be
    # included here - Problems.md bug: --calibrate-book-spread alone used
    # to also silently run a whole extra --rank-book simulation because it
    # wasn't counted as "a flag was given".
    if not (
        run_rank_book or run_capacity or run_stress or run_calibrate or run_ablation_flag
        or run_calibrate_book_spread or run_calibrate_confidence_threshold or run_replay_kill_switch
        or run_simulate_limit_fills
    ):
        run_rank_book = True

    report: dict = {}
    evaluation_dir = ML_DIR / "evaluation"

    if run_rank_book:
        result = simulate_rank_book(dataset, **base_kwargs)
        report["rank_book"] = result.to_dict()
        _write_evaluation_json(evaluation_dir / "rank_book_simulation.json", report["rank_book"])
        # Additive, per-model copy alongside the unsuffixed "last run" file
        # above (untouched - monitoring/evaluation_state.py's webui feed
        # and existing tests depend on that exact fixed name) - lets a
        # multitask run and a sequence run coexist on disk instead of the
        # second silently clobbering the first, for callers (e.g.
        # generate_evaluation_report.py) that want to compare both models
        # at once rather than only "whichever ran last".
        _write_evaluation_json(evaluation_dir / f"rank_book_simulation_{model_kind}.json", report["rank_book"])
        if not args.json:
            print(f"Rank book ({model_kind}/{head}, split={split}, entry_lag_bars={base_kwargs['entry_lag_bars']}):")
            print(f"  gross_sharpe={result.gross_sharpe:.4f}  net_sharpe={result.net_sharpe:.4f}")
            print(f"  gross_total_return={result.gross_total_return:.4%}  net_total_return={result.net_total_return:.4%}")
            print(f"  net_max_drawdown={result.net_max_drawdown:.4%}")
            print(f"  annualized_turnover={result.annualized_turnover:.2f}x  cost_drag_annual_bps={result.cost_drag_annual_bps:.2f}")
            print(f"  num_rebalances={result.num_rebalances}  num_dates_used={result.num_dates_used}")
            print(f"  mean_names_long={result.mean_names_long:.2f}  mean_names_short={result.mean_names_short:.2f}")

        # V5.2.1 (development/Problems.md) - a Daily-resolution market
        # order decided off bar N's close fills at bar N+1's open, not
        # bar N's close; this simulator's own return accrual previously
        # had no way to model that. ALWAYS compute and show both
        # entry_lag_bars=0 (same-bar fill, what this simulator has always
        # assumed) and =1 (the honest, next-bar-fill "lag tax") here,
        # regardless of what net_perf_config.entry_lag_bars is configured
        # to - so the gap this investigation found is never silently
        # invisible again, whichever value base_kwargs happens to carry.
        lag_kwargs = dict(base_kwargs)
        lag_kwargs["entry_lag_bars"] = 1
        lagged_result = simulate_rank_book(dataset, **lag_kwargs)
        report["rank_book_entry_lag_1"] = lagged_result.to_dict()
        _write_evaluation_json(evaluation_dir / "rank_book_simulation_entry_lag_1.json", report["rank_book_entry_lag_1"])
        _write_evaluation_json(
            evaluation_dir / f"rank_book_simulation_entry_lag_1_{model_kind}.json", report["rank_book_entry_lag_1"]
        )
        if not args.json:
            print(f"Rank book (entry_lag_bars=1, the 'lag tax' - see development/Problems.md):")
            print(f"  gross_sharpe={lagged_result.gross_sharpe:.4f}  net_sharpe={lagged_result.net_sharpe:.4f}")
            print(f"  delta_net_sharpe vs entry_lag_bars=0: {lagged_result.net_sharpe - result.net_sharpe:+.4f}")

    # V5.2.8 (development/Problems.md #94) - reuses --rank-book's own
    # `result` (per_date/per_date_net_return) when that flag was also
    # given, rather than recomputing simulate_rank_book() a second time;
    # computes it fresh (entry_lag_bars=0, the same default --rank-book
    # uses) when --replay-kill-switch is passed on its own.
    if run_replay_kill_switch:
        from evaluation.kill_switch_replay import (
            replay_kill_switch_over_dataset,
            summarize_kill_switch_replay,
        )

        kill_switch_replay_result = result if run_rank_book else simulate_rank_book(dataset, **base_kwargs)
        kill_switch_config = config.get("phase_v2", {}).get("risk", {}).get("kill_switch", {})
        phase6_risk = config.get("phase6", {}).get("risk", {})
        daily_portfolio_returns = dict(
            zip(kill_switch_replay_result.per_date, kill_switch_replay_result.per_date_net_return)
        )
        replay_records = replay_kill_switch_over_dataset(
            kill_switch_replay_result.per_date,
            daily_portfolio_returns,
            kill_switch_config,
            max_daily_drawdown_pct=float(phase6_risk.get("max_daily_drawdown_pct", 0.03)),
            max_total_drawdown_pct=float(phase6_risk.get("max_total_drawdown_pct", 0.12)),
        )
        replay_summary = summarize_kill_switch_replay(replay_records)
        report["kill_switch_replay"] = {"summary": replay_summary, "per_date": replay_records}
        _write_evaluation_json(evaluation_dir / "kill_switch_replay.json", report["kill_switch_replay"])
        if not args.json:
            print(
                f"Kill-switch replay (APPROXIMATION - see development/Problems.md #94): "
                f"{replay_summary['trip_count']} trips across {replay_summary['total_dates']} dates, "
                f"{replay_summary['locked_days']} locked days ({replay_summary['locked_day_fraction']:.2%})"
            )

    # V5.3.1 (development/Problems.md #34/#96) - offline counterfactual:
    # "how often would a real limit order have filled" without needing a
    # live Lean run. Deliberately independent of --rank-book above - it
    # simulates a signal firing on every row, not just book-selected ones
    # (see evaluation/limit_fill_simulator.py's own docstring for why
    # that's a different, complementary question, not a replay of the
    # real order-events.json evidence).
    if run_simulate_limit_fills:
        from evaluation.limit_fill_simulator import simulate_limit_fills, sweep_limit_fill_offsets

        limit_orders_config = config.get("phase_v2", {}).get("limit_orders", {})
        timeout_bars = int(limit_orders_config.get("unfilled_timeout_bars", 3))
        offset_sweep_arg = getattr(args, "limit_fill_offset_sweep", None)
        if offset_sweep_arg:
            offsets = [float(value) for value in offset_sweep_arg.split(",")]
            limit_fill_result = sweep_limit_fill_offsets(dataset, unfilled_timeout_bars=timeout_bars, offset_multipliers=offsets)
        else:
            configured_offset = float(limit_orders_config.get("offset_multiplier", 1.0))
            limit_fill_result = simulate_limit_fills(dataset, unfilled_timeout_bars=timeout_bars, offset_multiplier=configured_offset)
        report["limit_fill_simulation"] = limit_fill_result
        _write_evaluation_json(evaluation_dir / "limit_fill_simulation.json", limit_fill_result)
        if not args.json:
            print(f"Limit-fill simulation (APPROXIMATION, unfilled_timeout_bars={timeout_bars}):")
            if offset_sweep_arg:
                for multiplier, result_for_multiplier in limit_fill_result.items():
                    overall = result_for_multiplier["overall"]
                    print(
                        f"  offset_multiplier={multiplier}: fill_rate={overall['fill_rate']:.2%} "
                        f"timeout_rate={overall['timeout_rate']:.2%} num_signals={overall['num_signals']}"
                    )
            else:
                overall = limit_fill_result["overall"]
                print(
                    f"  overall: fill_rate={overall['fill_rate']:.2%} timeout_rate={overall['timeout_rate']:.2%} "
                    f"num_signals={overall['num_signals']}"
                )
                for security_type, stats in sorted(limit_fill_result["by_asset_class"].items()):
                    print(f"  {security_type}: fill_rate={stats['fill_rate']:.2%} num_signals={stats['num_signals']}")

    if run_capacity:
        cap = capacity_curve(
            dataset,
            participation_cap=float(net_perf_config.get("capacity_participation_cap", 0.01)),
            base_kwargs=base_kwargs,
            top_n_sweep=[int(n) for n in net_perf_config.get("capacity_top_n_sweep", [3, 6, 10, 15])],
        )
        report["capacity"] = cap
        _write_evaluation_json(evaluation_dir / "capacity_report.json", cap)
        _write_evaluation_json(evaluation_dir / f"capacity_report_{model_kind}.json", cap)
        if not args.json:
            print(f"Capacity: ${cap['capacity_usd']:,.0f} (binding: {cap['binding_ticker']})")
            for row in cap["per_top_n"]:
                print(f"  top_n={row['top_n']}: net_sharpe={row['net_sharpe']:.4f}")

    if run_stress:
        stress = stress_test_costs(
            dataset, base_kwargs=base_kwargs,
            cost_multipliers=tuple(float(m) for m in net_perf_config.get("stress_cost_multipliers", [1.0, 2.0, 3.0])),
        )
        report["stress"] = stress
        _write_evaluation_json(evaluation_dir / "cost_stress_report.json", {"stress": stress})
        _write_evaluation_json(evaluation_dir / f"cost_stress_report_{model_kind}.json", {"stress": stress})
        if not args.json:
            print("Cost stress test:")
            for row in stress:
                print(f"  {row['cost_multiplier']}x: net_sharpe={row['net_sharpe']:.4f}  net_total_return={row['net_total_return']:.4%}")

    if run_calibrate:
        # A simple OLS slope-through-the-origin of forward return on
        # (rank - 0.5)*2 - matches execution/cost_model.py::expected_edge_bps()'s
        # own linear-in-rank-deviation model. That function documents its
        # edge_bps_per_rank_unit as the FULL predicted move over
        # phase_v2.costs.horizon_days (it then scales down by
        # holding_bars/horizon_days itself) - so the regression must use
        # the SAME horizon's forward return, not a fixed 1-day one, or the
        # calibrated number is off by roughly horizon_days/1 (a ~20x
        # understatement of edge at the default horizon_days=20, since a
        # 1-day slope was previously being treated as a 20-day move and
        # then halved again downstream).
        costs_config = config.get("phase_v2", {}).get("costs", {})
        horizon_days = int(costs_config.get("horizon_days", 20))
        forward_return_column = f"target_return_{horizon_days}d"
        if forward_return_column not in dataset.columns:
            print(
                f"warning: {forward_return_column!r} not in dataset (horizon_days={horizon_days}); "
                "falling back to target_return_1d - the calibrated value will then represent a "
                "1-day move, not the horizon_days move expected_edge_bps() assumes.",
                file=sys.stderr,
            )
            forward_return_column = "target_return_1d"
        rank_deviation = (dataset["predicted_head"] - 0.5) * 2.0
        forward_return = dataset[forward_return_column]
        valid = rank_deviation.notna() & forward_return.notna()
        x = rank_deviation[valid].to_numpy()
        y = forward_return[valid].to_numpy()
        denominator = float((x * x).sum()) if len(x) >= 2 else 0.0
        slope = float((x * y).sum() / denominator) if denominator > 0 else 0.0
        calibrated_edge_bps = slope * 10_000.0
        report["calibrated_edge_bps_per_rank_unit"] = calibrated_edge_bps
        report["calibrated_edge_forward_return_column"] = forward_return_column
        if not args.json:
            print(f"Calibrated edge_bps_per_rank_unit ({forward_return_column}): {calibrated_edge_bps:.4f}")
            print(f"  Apply with: aq config set phase_v2.costs.edge_bps_per_rank_unit {calibrated_edge_bps:.4f}")
            print("  Then enable the gate: aq config set phase_v2.costs.enabled true")

    if run_calibrate_book_spread:
        # V5.1 (development/Problems.md) - min_rank_confidence_spread was a
        # guessed constant (0.2) never checked against this codebase's
        # actual raw-score scale; evaluation/rank_book_simulator.py's own
        # book simulation hardcodes min_rank_confidence_spread=0.0 (see
        # that module's comment), so nothing ever exercised the real gate
        # before it shipped live. This mirrors --calibrate-edge's own
        # discipline: derive the number from data, don't guess it.
        from evaluation import calibrate_book_confidence_spread, compute_blended_raw_scores
        from portfolio.rank_signal import resolve_rank_signal_policy

        rank_signal_config = config.get("phase_v2", {}).get("rank_signal", {})
        training_metrics_by_model: dict[str, dict | None] = {}
        for model_name, metrics_filename in (
            ("sequence", "sequence_training_metrics.json"),
            ("multitask", "multitask_training_metrics.json"),
        ):
            metrics_path = ML_DIR / metrics_filename
            training_metrics_by_model[model_name] = (
                json.loads(metrics_path.read_text(encoding="utf-8")) if metrics_path.exists() else None
            )
        policy = resolve_rank_signal_policy(training_metrics_by_model, config)
        active_heads = [head_name for head_name, weight in policy["heads"].items() if weight > 0.0]

        predictions_by_model_head: dict[str, dict[str, object]] = {}
        for model_kind_for_head in policy["model_priority"]:
            calib_model_filename, calib_schema_filename = _EVALUATE_MODEL_ARTIFACTS[model_kind_for_head]
            calib_model_path = ML_DIR / calib_model_filename
            calib_schema_path = ML_DIR / calib_schema_filename
            if not calib_model_path.exists() or not calib_schema_path.exists():
                continue  # best-effort - a missing model just means its heads fall through to the next model_priority entry
            calib_model_export = json.loads(calib_model_path.read_text(encoding="utf-8"))
            calib_feature_schema = json.loads(calib_schema_path.read_text(encoding="utf-8"))
            calib_feature_names = calib_feature_schema["model_input_names"]
            head_predictions: dict[str, object] = {}
            for head_name in active_heads:
                head_predictions[head_name] = predict_head(
                    dataset, calib_model_export, calib_feature_names, head_name,
                    model_kind=model_kind_for_head,
                    sequence_feature_schema=calib_feature_schema if model_kind_for_head == "sequence" else None,
                    configured_window_size=int(sequence_window_default),
                )
            predictions_by_model_head[model_kind_for_head] = head_predictions

        dataset["raw_blended_score"] = compute_blended_raw_scores(dataset, predictions_by_model_head, policy)

        book_config = config.get("phase_v2", {}).get("portfolio_book", {})
        strategy_mode = config.get("phase5", {}).get("backtest", {}).get("strategy_mode", "long_flat")
        book_top_n = int(book_config.get("top_n", 6))
        book_bottom_n = int(book_config.get("bottom_n", 6)) if strategy_mode == "long_short" else 0

        book_spread_result = calibrate_book_confidence_spread(
            dataset,
            raw_score_column="raw_blended_score",
            top_n=book_top_n,
            bottom_n=book_bottom_n,
            percentile=float(getattr(args, "book_spread_percentile", 0.10)),
        )
        report["book_spread_calibration"] = book_spread_result
        _write_evaluation_json(evaluation_dir / "book_spread_calibration.json", book_spread_result)
        if not args.json:
            calibrated_spread = book_spread_result["calibrated_min_rank_confidence_spread"]
            distribution = book_spread_result["spread_distribution"]
            print(
                f"Calibrated min_rank_confidence_spread (p{book_spread_result['percentile']*100:.0f}, "
                f"{book_spread_result['num_dates_used']} dates used, "
                f"{book_spread_result['num_dates_skipped_thin_universe']} skipped thin-universe): "
                f"{calibrated_spread:.4f}"
            )
            print(
                f"  Distribution: min={distribution['min']}, p10={distribution['p10']}, "
                f"median={distribution['median']}, p75={distribution['p75']}, max={distribution['max']}"
            )
            print(f"  Apply with: aq config set phase_v2.portfolio_book.min_rank_confidence_spread {calibrated_spread:.4f}")
            print(
                "  NOTE: this recalibrates the gate's threshold to this model's real achievable dispersion - "
                "it does not certify the underlying rank heads are skillful. Check ml/*_training_metrics.json's "
                "quality_status before trusting the resulting book."
            )

    if run_calibrate_confidence_threshold:
        # V5.2.6 (development/Problems.md) - min_confidence_to_trade was a
        # guessed constant (0.12), never checked against this codebase's
        # actual confidence-vs-forward-return relationship - the same
        # "guessed constant, never calibrated" problem
        # min_rank_confidence_spread had (Problems.md #89) before
        # --calibrate-book-spread fixed it. Mirrors that tool's exact
        # structure.
        from evaluation import calibrate_confidence_threshold, compute_blended_raw_scores
        from portfolio.rank_signal import resolve_rank_signal_policy

        rank_signal_config = config.get("phase_v2", {}).get("rank_signal", {})
        training_metrics_by_model: dict[str, dict | None] = {}
        for model_name, metrics_filename in (
            ("sequence", "sequence_training_metrics.json"),
            ("multitask", "multitask_training_metrics.json"),
        ):
            metrics_path = ML_DIR / metrics_filename
            training_metrics_by_model[model_name] = (
                json.loads(metrics_path.read_text(encoding="utf-8")) if metrics_path.exists() else None
            )
        policy = resolve_rank_signal_policy(training_metrics_by_model, config)
        active_heads = [head_name for head_name, weight in policy["heads"].items() if weight > 0.0]

        predictions_by_model_head: dict[str, dict[str, object]] = {}
        for model_kind_for_head in policy["model_priority"]:
            calib_model_filename, calib_schema_filename = _EVALUATE_MODEL_ARTIFACTS[model_kind_for_head]
            calib_model_path = ML_DIR / calib_model_filename
            calib_schema_path = ML_DIR / calib_schema_filename
            if not calib_model_path.exists() or not calib_schema_path.exists():
                continue  # best-effort - a missing model just means its heads fall through to the next model_priority entry
            calib_model_export = json.loads(calib_model_path.read_text(encoding="utf-8"))
            calib_feature_schema = json.loads(calib_schema_path.read_text(encoding="utf-8"))
            calib_feature_names = calib_feature_schema["model_input_names"]
            head_predictions: dict[str, object] = {}
            for head_name in active_heads:
                head_predictions[head_name] = predict_head(
                    dataset, calib_model_export, calib_feature_names, head_name,
                    model_kind=model_kind_for_head,
                    sequence_feature_schema=calib_feature_schema if model_kind_for_head == "sequence" else None,
                    configured_window_size=int(sequence_window_default),
                )
            predictions_by_model_head[model_kind_for_head] = head_predictions

        dataset["raw_blended_score"] = compute_blended_raw_scores(dataset, predictions_by_model_head, policy)

        book_config = config.get("phase_v2", {}).get("portfolio_book", {})
        strategy_mode = config.get("phase5", {}).get("backtest", {}).get("strategy_mode", "long_flat")
        book_top_n = int(book_config.get("top_n", 6))
        book_bottom_n = int(book_config.get("bottom_n", 6)) if strategy_mode == "long_short" else 0

        confidence_forward_return_column = "target_return_20d"
        if confidence_forward_return_column not in dataset.columns:
            print(
                f"warning: {confidence_forward_return_column!r} not in dataset; falling back to "
                "target_return_1d - the calibrated value will then represent a 1-day move, not the "
                "20-day move predicted_rank_20d assumes.",
                file=sys.stderr,
            )
            confidence_forward_return_column = "target_return_1d"

        confidence_result = calibrate_confidence_threshold(
            dataset,
            raw_score_column="raw_blended_score",
            forward_return_column=confidence_forward_return_column,
            top_n=book_top_n,
            bottom_n=book_bottom_n,
            round_trip_cost_fraction=float(
                config.get("phase_v2", {}).get("liquidity", {}).get("max_round_trip_cost_fraction") or 0.001
            ),
            percentile=float(getattr(args, "confidence_threshold_percentile", 0.10)),
        )
        report["confidence_threshold_calibration"] = confidence_result
        _write_evaluation_json(evaluation_dir / "confidence_threshold_calibration.json", confidence_result)
        if not args.json:
            calibrated_general = confidence_result["calibrated_min_confidence_to_trade"]
            calibrated_book_selected = confidence_result["calibrated_min_confidence_to_trade_book_selected"]
            print(
                f"Calibrated min_confidence_to_trade (p{confidence_result['percentile']*100:.0f}, "
                f"{confidence_result['num_rows_used']} paying rows used, "
                f"{confidence_result['num_dates_skipped_thin_universe']} dates skipped thin-universe): "
                f"{calibrated_general:.4f}"
            )
            print(
                f"Calibrated min_confidence_to_trade_book_selected ({confidence_result['num_rows_used_book_selected']} "
                f"paying book-selected rows used): {calibrated_book_selected:.4f}"
            )
            print(f"  Apply with: aq config set phase6.risk.min_confidence_to_trade {calibrated_general:.4f}")
            print(
                "  Apply with: aq config set phase6.risk.min_confidence_to_trade_book_selected "
                f"{calibrated_book_selected:.4f}"
            )
            print(
                "  NOTE: this recalibrates the gate's threshold to this model's real achievable confidence "
                "among historically-paying trades - it does not certify the underlying rank heads are "
                "skillful. Check ml/*_training_metrics.json's quality_status before trusting the result."
            )

    if run_ablation_flag:
        from evaluation import run_ablation

        ablation_config = config.get("phase_v2", {}).get("evaluation", {}).get("ablation", {})
        requested_variants = (
            [name.strip() for name in args.variants.split(",") if name.strip()]
            if getattr(args, "variants", None)
            else list(ablation_config.get("variants", ["static_baseline", "no_neutrality", "no_hysteresis", "no_cost_model"]))
        )
        ablation_results = run_ablation(dataset, base_kwargs, requested_variants)
        report["ablation"] = ablation_results
        _write_evaluation_json(
            ROOT_DIR / ablation_config.get("report_path", "ml/evaluation/ablation_report.json"), ablation_results
        )
        if not args.json:
            print(f"Ablation ({model_kind}/{head}, split={split}):")
            for name, entry in ablation_results.items():
                if entry.get("status") in {"not_offline_measurable", "unknown_variant", "insufficient_windows"}:
                    print(f"  {name}: [{entry['status']}] {entry.get('reason', '')}")
                else:
                    print(f"  {name}: net_sharpe={entry['net_sharpe']:.4f}  delta_vs_static_baseline={entry['delta_vs_static_baseline']:+.4f}")

    if args.json:
        print(json.dumps(report, indent=2, default=str))

    _refresh_readme_evaluation_sections()
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
        "--topology-only",
        action="store_true",
        help=(
            "Train the learned topology overlay only (wraps python train_topology.py). Needs Postgres up "
            "and enough accumulated realized-outcome events - see the command's own output if it skips."
        ),
    )
    train_group.add_argument(
        "--strategy-selector-only",
        action="store_true",
        help=(
            "Train the learned multi-leg strategy-selector model only (wraps python "
            "train_strategy_selector.py, V4.7, development/Problems.md #29's own framing). Needs real "
            "option_strategy_outcome events (real option positions traded and closed) - expect this to "
            "skip indefinitely in this environment, see the command's own output."
        ),
    )
    train_group.add_argument(
        "--rl-sizing-only",
        action="store_true",
        help=(
            "Train the offline contextual-bandit sizing overlay only (wraps python train_rl_sizing.py, "
            "development/Problems.md #71). Reads ml/datasets/*.csv, NOT Postgres - needs a completed "
            "`aq train` and Component D's alt-data features in phase1.features.input_set."
        ),
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
    # V5.1 Phase 4 (item 4) - one-run overrides of config.json's
    # phase_v2.retraining.walk_forward.{train_multitask,train_sequence,
    # tracked_metrics}, only meaningful with --walk-forward - passthrough
    # to train.py --walk-forward's own identical flags.
    train_parser.add_argument(
        "--include-multitask",
        action="store_true",
        help="Force multitask training per walk-forward window on for this run (only with --walk-forward).",
    )
    train_parser.add_argument(
        "--include-sequence",
        action="store_true",
        help="Force sequence training per walk-forward window on for this run (only with --walk-forward).",
    )
    train_parser.add_argument(
        "--metrics",
        type=str,
        default=None,
        help=(
            "Comma-separated tracked-metric names to restrict walk-forward tracking to for this run "
            "(only with --walk-forward)."
        ),
    )
    # V5.1 Phase 3 (item 1) - passthrough to --multitask-only/--sequence-only's
    # own train_multitask.py/train_sequence.py --seed/--ranking-objective
    # flags (development/Problems.md - previously the seed-ensembling
    # workflow required calling those scripts directly, bypassing `aq`
    # entirely). Ignored (with a warning) by every other --*-only mode and
    # by the default full-pipeline train.py invocation, neither of which
    # accepts these flags.
    train_parser.add_argument(
        "--seed", type=int, default=None, help="Override config.json's seed (only with --multitask-only/--sequence-only)"
    )
    train_parser.add_argument(
        "--ranking-objective",
        type=str,
        default=None,
        choices=["mse", "soft_spearman", "listnet"],
        help="Override config.json's ranking_loss.objective for this run only (only with --multitask-only/--sequence-only)",
    )
    train_parser.set_defaults(func=cmd_train)

    test_parser = subparsers.add_parser("test", help="Run the test suite (wraps pytest tests/)")
    test_parser.add_argument(
        "--lean", "--full", dest="lean", action="store_true",
        help="Include the real `lean backtest .` integration test (tests/test_lean_backtest_ml_coverage.py, over an hour wall-clock) - excluded by default",
    )
    test_parser.add_argument(
        "--parallel", action="store_true",
        help="Run via pytest-xdist (-n auto) - off by default, multiple workers importing torch risk OOM on memory-constrained machines",
    )
    for _subsystem_name in _SUBSYSTEM_TEST_FILES:
        test_parser.add_argument(
            f"--{_subsystem_name}",
            action="store_true",
            help=f"Run only the {_subsystem_name} subsystem's tests ({', '.join(_SUBSYSTEM_TEST_FILES[_subsystem_name][:2])}, ...)",
        )
    test_parser.set_defaults(func=cmd_test)

    backtest_parser = subparsers.add_parser("backtest", help="Run a Lean backtest (wraps lean backtest .)")
    backtest_parser.add_argument(
        "--image",
        default=None,
        help=f"Override the Lean engine Docker image (default: pinned {PINNED_LEAN_ENGINE_IMAGE}, "
        "never the mutable :latest tag - see PINNED_LEAN_ENGINE_IMAGE's comment in aq_cli.py)",
    )
    backtest_parser.set_defaults(func=cmd_backtest)

    profile_parser = subparsers.add_parser(
        "profile",
        help="Profile the per-bar hot path (wraps scripts/profile_inference.py / scripts/profile_subsystems.py)",
    )
    # default=None (not 10_000/200) so cmd_profile() can tell "user didn't
    # pass --iterations" apart from "user explicitly passed the same
    # number" and let whichever script actually runs use ITS OWN default -
    # profile_inference.py's 10,000 (cheap ~5ms/call) and
    # profile_subsystems.py's 200 (build_market_topology() alone costs
    # ~500-600ms/call at this project's real universe size - 10,000 there
    # would take over an hour) are deliberately very different, and
    # hardcoding either one here would silently override the other.
    profile_parser.add_argument(
        "--iterations", type=int, default=None,
        help="Iterations to profile (default: 10000 for inference, 200 for --<subsystem> flags)",
    )
    profile_parser.add_argument("--sort", default="cumulative", help="pstats sort key (default: cumulative)")
    profile_parser.add_argument(
        "--batched", action="store_true",
        help="Use the batched expert-inference path (with its precomputed stack caches) instead of a per-expert loop",
    )
    profile_parser.add_argument(
        "--no-gc", action="store_true",
        help="Disable the GC around the profiled region, to isolate whether GC pauses drive tail latency (inference only)",
    )
    profile_parser.add_argument(
        "--bucket-report", action="store_true",
        help="Print a 10-bucket-by-iteration-index duration breakdown, to check for a warmup effect (inference only)",
    )
    profile_parser.add_argument(
        "--parallel", action="store_true",
        help="V4.9 Priority 6: run the ProcessPoolExecutor IPC-overhead benchmark against run_symbol_inference() (inference only)",
    )
    profile_parser.add_argument(
        "--pool-workers", type=int, default=None,
        help="Worker process count for --parallel (default: profile_inference.py's own default, 4)",
    )
    profile_parser.add_argument(
        "--symbols-per-bar", type=int, default=None,
        help="Symbols-per-bar grouping for --batched's sequence-batching comparison and --parallel's benchmark (default: profile_inference.py's own default, 74)",
    )
    for _profile_subsystem_name in _PROFILE_SUBSYSTEM_FLAGS:
        profile_parser.add_argument(
            f"--{_profile_subsystem_name}",
            action="store_true",
            help=f"Profile only the {_profile_subsystem_name} subsystem (scripts/profile_subsystems.py)",
        )
    profile_parser.set_defaults(func=cmd_profile)

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

    docker_build_parser = docker_subparsers.add_parser(
        "build", help="Rebuild the consolidated aether-quant-engine image (app + every worker)"
    )
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

    # V5.1 Phase 1 - phase_v2.presets, named dotted-key-override blocks
    # (e.g. "aggressive"/"moderate" turnover profiles). config-only, no
    # `aq lean preset` equivalent.
    config_preset_parser = config_subparsers.add_parser(
        "preset", help="List/show/apply a named config preset (phase_v2.presets)"
    )
    config_preset_group = config_preset_parser.add_mutually_exclusive_group()
    config_preset_group.add_argument("--list", dest="preset_list", action="store_true", help="List available presets")
    config_preset_group.add_argument("--show", dest="preset_show", metavar="NAME", help="Print one preset's overrides")
    config_preset_group.add_argument(
        "--apply", dest="preset_apply", metavar="NAME", help="Apply one preset's overrides to config.json"
    )
    config_preset_parser.add_argument(
        "--dry-run", dest="preset_dry_run", action="store_true", help="With --apply: print old -> new, write nothing"
    )

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
            "train_strategy_selector",
            "validate",
            "backtest",
            "commit",
            "promote",
            "rollback",
            "status",
            # V5.1 Phase 6 (production safety) - read-only diagnostic,
            # never itself calls rollback() - see retraining/orchestrator.py::
            # auto_rollback_status()'s own docstring.
            "auto-rollback",
        ],
    )
    retrain_parser.add_argument("retrain_args", nargs=argparse.REMAINDER, help="Passed through verbatim, e.g. --version-id <uuid>")
    retrain_parser.set_defaults(func=cmd_retrain)

    backfill_parser = subparsers.add_parser(
        "backfill",
        help=(
            "Thin dispatcher to python -m data_pipeline.<target>_backfill ... (whole-universe bulk "
            "backfills). Different from `aq fetch`, which is for one ad-hoc ticker."
        ),
    )
    backfill_parser.add_argument("target", choices=["dividends", "fred", "yfinance"])
    backfill_parser.add_argument(
        "backfill_args",
        nargs=argparse.REMAINDER,
        help="Passed through verbatim, e.g. --apply --tickers AAPL MSFT (dividends/yfinance), or --series DGS10 (fred)",
    )
    backfill_parser.set_defaults(func=cmd_backfill)

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

    # V5.1 Phase 6 (production safety) - deliberately the same
    # override-file/mutually-exclusive-group shape as `trade-lock` above (see
    # risk/manual_override.py's kill_switch_manual_override, the exact same
    # read/write/cache convention as manual_trade_lock_override) so the two
    # switches can never disagree about their CLI surface. --history is the
    # one addition, querying the tamper-evident audit log instead.
    kill_switch_parser = subparsers.add_parser(
        "kill-switch", help="Manually override / inspect the automated production kill switch"
    )
    kill_switch_group = kill_switch_parser.add_mutually_exclusive_group(required=True)
    kill_switch_group.add_argument("--arm", action="store_true", help="Force kill-switch evaluation on")
    kill_switch_group.add_argument("--disarm", action="store_true", help="Force kill-switch evaluation off")
    kill_switch_group.add_argument("--auto", action="store_true", help="Defer to phase_v2.risk.kill_switch.enabled")
    kill_switch_group.add_argument("--status", dest="status", action="store_true", help="Print the current override state")
    kill_switch_group.add_argument("--history", action="store_true", help="List recorded kill-switch trips from the audit log")
    kill_switch_parser.add_argument("--limit", type=int, default=50, help="Max --history rows (default 50)")
    kill_switch_parser.set_defaults(func=cmd_kill_switch)

    fetch_parser = subparsers.add_parser(
        "fetch",
        help=(
            "Ad-hoc fetch of historical OHLCV from Yahoo Finance for a ticker not yet in config.json. "
            "For a whole-universe bulk refresh instead (dividends/FRED series/Yahoo gaps), see `aq backfill`."
        ),
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
    fetch_parser.add_argument(
        "--contract-month", default=None,
        help="Futures only: YYYYMM - fetch a specific dated contract instead of the continuous front-month "
        "(e.g. for building real historical term structure with a second, later --contract-month fetch under "
        "the same --family-ticker)",
    )
    fetch_parser.add_argument(
        "--family-ticker", default=None,
        help="Groups multiple fetched contracts under one root for offline training's derivatives-macro features "
        "(train.py::build_derivatives_macro_features_by_date()) - e.g. two futures/options fetches sharing "
        "--family-ticker ES. Defaults to --ticker itself (a single, ungrouped contract).",
    )
    fetch_parser.set_defaults(func=cmd_fetch)

    ib_parser = subparsers.add_parser("ib", help="Check Interactive Brokers configuration/connectivity")
    ib_subparsers = ib_parser.add_subparsers(dest="ib_command", required=True)
    ib_subparsers.add_parser("status", help="Report disabled / credentials-missing / reachable")
    ib_parser.set_defaults(func=cmd_ib)

    assets_parser = subparsers.add_parser("assets", help="Report multi-asset-class (futures/options/FRED) readiness")
    assets_subparsers = assets_parser.add_subparsers(dest="assets_command", required=True)
    assets_subparsers.add_parser("status", help="Report IB/futures/options/FRED readiness at a glance")
    assets_parser.set_defaults(func=cmd_assets)

    evaluate_parser = subparsers.add_parser(
        "evaluate",
        help="Offline, cost-aware evaluation of the cross-sectional rank book (V5.1) - net Sharpe/turnover/"
        "capacity/cost-stress from the active model + dataset, without a Lean backtest",
    )
    evaluate_parser.add_argument("--rank-book", action="store_true", help="Simulate the rank book net of costs")
    evaluate_parser.add_argument("--capacity", action="store_true", help="Breadth (top_n sweep) + capacity estimate")
    evaluate_parser.add_argument("--stress", action="store_true", help="Re-run at 1x/2x/3x the configured cost")
    evaluate_parser.add_argument(
        "--calibrate-edge", action="store_true",
        help="Print an edge_bps_per_rank_unit calibrated from this split's realized rank-vs-return relationship",
    )
    evaluate_parser.add_argument("--all", action="store_true", help="Run --rank-book, --capacity, --stress and --calibrate-edge together")
    evaluate_parser.add_argument(
        "--walk-forward-summary", action="store_true",
        help="Print an already-written ml/versions/walk-forward-*/walk_forward_summary.json (V5.1 Phase 4) - "
        "never runs training itself; run `aq train --walk-forward` first.",
    )
    evaluate_parser.add_argument(
        "--run-id", default=None,
        help="Specific walk-forward run-id to read with --walk-forward-summary (default: the most recent run).",
    )
    evaluate_parser.add_argument(
        "--ablation", action="store_true",
        help="V5.1 Phase 5: run the adaptive-machinery ablation harness - runtime-only mechanisms "
        "(gating, topology sizing, the net-edge gate, ...) honestly report not_offline_measurable "
        "rather than a fabricated number. Not included in --all.",
    )
    evaluate_parser.add_argument(
        "--variants", default=None,
        help="Comma-separated ablation variant names to run with --ablation (default: "
        "phase_v2.evaluation.ablation.variants from config.json).",
    )
    evaluate_parser.add_argument(
        "--calibrate-book-spread", action="store_true",
        help="Print a min_rank_confidence_spread calibrated from this split's actual raw-score dispersion "
        "(the same resolved rank-signal blend and book top_n/bottom_n main.py uses live). Not included in "
        "--all - loads both models' predictions, a heavier run like --ablation.",
    )
    evaluate_parser.add_argument(
        "--book-spread-percentile", type=float, default=0.10,
        help="Percentile (0-1) of the per-date confidence-spread distribution to use as the calibrated "
        "floor with --calibrate-book-spread (default: 0.10).",
    )
    evaluate_parser.add_argument(
        "--calibrate-confidence-threshold", action="store_true",
        help="Print a min_confidence_to_trade (and, when book-selection data is available, a separate "
        "min_confidence_to_trade_book_selected) calibrated from this split's real confidence-vs-forward-"
        "return relationship, mirroring --calibrate-book-spread's discipline. Not included in --all.",
    )
    evaluate_parser.add_argument(
        "--confidence-threshold-percentile", type=float, default=0.10,
        help="Percentile (0-1) of the paying-trade confidence distribution to use as the calibrated floor "
        "with --calibrate-confidence-threshold (default: 0.10).",
    )
    evaluate_parser.add_argument(
        "--reconcile-book-history", action="store_true",
        help="V5.2.2: compare a real Lean backtest's logged book selections "
        "(phase_v2.diagnostics.book_history) against a fresh offline re-derivation of the same raw "
        "scores on those same dates - true ground truth for diagnosing offline-vs-live divergence. "
        "Not included in --all - loads both models' predictions like --calibrate-book-spread.",
    )
    evaluate_parser.add_argument(
        "--book-history-path", default=None,
        help="Path to the book_history.jsonl log to reconcile with --reconcile-book-history "
        "(default: phase_v2.diagnostics.book_history.output_path from config.json).",
    )
    evaluate_parser.add_argument(
        "--replay-hysteresis", action="store_true",
        help="V5.2.3: with --reconcile-book-history, replay offline's own hysteresis-aware selection "
        "walk-forward across the log's dates (carrying held allocations forward, same as main.py's live "
        "book) instead of reconciling each date independently - tells a real divergence apart from the "
        "live book correctly holding an incumbent a from-scratch reselection wouldn't naturally pick.",
    )
    reconcile_run_group = evaluate_parser.add_mutually_exclusive_group()
    reconcile_run_group.add_argument(
        "--reconcile-run-index", type=int, default=None,
        help="V5.3.2: with --reconcile-book-history, reconcile only the run at this 0-indexed position "
        "within the log's own run-segmented history (negative indices count from the end, -1 == most "
        "recent - the default). book_history.jsonl is a cumulative, never-rotated log - every historical "
        "real backtest's records are appended forever - so reconciling without this flag defaults to the "
        "LATEST run only, never a silent cross-run merge (development/Problems.md #91/#97/#99).",
    )
    reconcile_run_group.add_argument(
        "--reconcile-all-runs", action="store_true",
        help="V5.3.2: with --reconcile-book-history, reconcile EVERY run segment independently (each its "
        "own held-allocations/summary, never merged across a run boundary) instead of just the most "
        "recent - for investigating an older run's own numbers, not for combining them into one figure.",
    )
    evaluate_parser.add_argument(
        "--replay-kill-switch", action="store_true",
        help="V5.2.8: day-by-day OFFLINE replay of the kill-switch + sticky trade-lock state machine "
        "(evaluation/kill_switch_replay.py) against the rank book's own simulated return series - an "
        "explicitly approximate estimate of how much of the run would have been locked out, without "
        "needing a real Lean backtest. Not included in --all - investigation-only, see development/"
        "Problems.md #94 for the caveats.",
    )
    evaluate_parser.add_argument(
        "--simulate-limit-fills", action="store_true",
        help="V5.3.1: offline counterfactual (evaluation/limit_fill_simulator.py) estimating how often a "
        "real limit order would fill vs. time out, using the existing dataset's own high/low bars and "
        "phase_v2.limit_orders' pricing/timeout config - without needing a real Lean backtest. Not "
        "included in --all - investigation-only, see development/Problems.md #34/#96 for the caveats.",
    )
    evaluate_parser.add_argument(
        "--limit-fill-offset-sweep", default=None,
        help="Comma-separated offset_multiplier values to sweep with --simulate-limit-fills (default: a "
        "single run at the configured phase_v2.limit_orders.offset_multiplier).",
    )
    evaluate_parser.add_argument("--model", choices=["sequence", "multitask"], default=None, help="Default: sequence")
    evaluate_parser.add_argument("--head", default=None, help="Model head to evaluate, e.g. rank_20d/rank_5d (default: rank_20d)")
    evaluate_parser.add_argument("--split", default=None, help="Dataset split to evaluate: train/validation/backtest/all (default: backtest)")
    evaluate_parser.add_argument(
        "--preset", default=None,
        help="Overlay phase_v2.presets.<name> in memory only (never writes config.json) - see `aq config preset --list`",
    )
    evaluate_parser.add_argument("--json", action="store_true", help="Print the full report as JSON instead of a summary")
    evaluate_parser.set_defaults(func=cmd_evaluate)

    render_lean_parser = subparsers.add_parser(
        "render-lean-config",
        help="Render gitignored lean.live.json from .env.live / AETHER_* env vars (secrets for live/paper)",
    )
    render_lean_parser.add_argument("--base", default=None, help="Empty tracked template (default: lean.json)")
    render_lean_parser.add_argument("--out", default=None, help="Rendered secret-bearing output (default: lean.live.json)")
    render_lean_parser.add_argument("--env-file", dest="env_file", default=None, help="Secrets file (default: .env.live)")
    render_lean_parser.set_defaults(func=cmd_render_lean_config)

    secrets_check_parser = subparsers.add_parser(
        "secrets-check",
        help="Fail if a populated secret field in lean.json or a tracked .env is about to be committed (backs the pre-commit hook)",
    )
    secrets_check_parser.set_defaults(func=cmd_secrets_check)

    audit_log_parser = subparsers.add_parser(
        "audit-log",
        help="Query the tamper-evident audit log (order placement, credential loads, live-mode transitions)",
    )
    audit_log_parser.add_argument("--event-type", dest="event_type", default=None,
                                   choices=["order_placement", "credential_load", "live_mode_transition"],
                                   help="Filter to one event type (default: all)")
    audit_log_parser.add_argument("--since", default=None, type=_iso_date, help="Only entries after this date, ISO 8601 YYYY-MM-DD")
    audit_log_parser.add_argument("--limit", type=int, default=100, help="Max entries to show (default: 100)")
    audit_log_parser.add_argument("--verify", action="store_true", help="Walk the whole hash chain and report the first break, if any")
    audit_log_parser.set_defaults(func=cmd_audit_log)

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
