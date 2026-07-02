"""Filesystem-only artifact helpers for candidate models (Phase V2-17).

No Postgres dependency here - this module only touches ml/versions/<id>/
and the active ml/ paths. Kept independent of train.py's own path constants
(rather than importing them) so retraining/ stays a lightweight package that
never pulls in torch/pandas/sklearn - only retraining/orchestrator.py's
`train` subcommand actually invokes train.py, and it does so as a
subprocess, not an import.
"""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
ML_DIR = ROOT_DIR / "ml"
VERSIONS_DIR = ML_DIR / "versions"

REQUIRED_CANDIDATE_FILES = (
    "model_weights.json",
    "model.pt",
    "training_metrics.json",
    "strategy_report.json",
    "scaler.pkl",
    "scaler_stats.json",
    "feature_schema.json",
)

# Files copied into the active ml/ directory on promotion/rollback. Extended
# beyond model_weights.json/scaler.pkl/training_metrics.json (the user's
# literal 3-file list) because main.py's _validate_runtime_artifacts()
# actually requires feature_schema.json and scaler_stats.json too - omitting
# them would let promotion silently break the Lean runtime.
ACTIVE_ARTIFACT_FILES = (
    "model_weights.json",
    "scaler.pkl",
    "scaler_stats.json",
    "training_metrics.json",
    "feature_schema.json",
)


def candidate_dir(version_id: str, ml_dir: Path = ML_DIR) -> Path:
    return ml_dir / "versions" / version_id


def check_required_artifacts(
    version_dir: Path, filenames: tuple[str, ...] = REQUIRED_CANDIDATE_FILES
) -> tuple[bool, list[str]]:
    """Returns (all_present, missing_filenames)."""
    missing = [name for name in filenames if not (version_dir / name).exists()]
    return (len(missing) == 0, missing)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def compute_artifact_hashes(
    version_dir: Path, filenames: tuple[str, ...] = REQUIRED_CANDIDATE_FILES
) -> dict[str, str]:
    """sha256 per file (only for files that exist) - feeds model_versions.artifact_hashes."""
    return {name: _sha256_file(version_dir / name) for name in filenames if (version_dir / name).exists()}


def copy_candidate_to_active(
    version_dir: Path,
    ml_dir: Path = ML_DIR,
    filenames: tuple[str, ...] = ACTIVE_ARTIFACT_FILES,
) -> dict[str, str]:
    """Copies the promotion artifact set from a candidate dir into ml/.

    Returns the new active artifact hashes (post-copy, from the destination
    files) for storage on the newly-promoted model_versions row.
    """
    ml_dir.mkdir(parents=True, exist_ok=True)
    hashes: dict[str, str] = {}
    for name in filenames:
        source = version_dir / name
        if not source.exists():
            continue
        destination = ml_dir / name
        shutil.copy2(source, destination)
        hashes[name] = _sha256_file(destination)
    return hashes


def restore_active_from_version(
    version_dir: Path,
    ml_dir: Path = ML_DIR,
    filenames: tuple[str, ...] = ACTIVE_ARTIFACT_FILES,
    expected_hashes: dict[str, str] | None = None,
) -> dict:
    """Rollback primitive - copies version_dir's files into ml/, verifying
    sha256 against expected_hashes BEFORE activation if hashes are given.

    Returns {"ok": bool, "hashes": {...}, "mismatched": [...]}. Never
    partially activates: if any expected hash mismatches, no files are
    copied at all.
    """
    if expected_hashes:
        mismatched = []
        for name, expected in expected_hashes.items():
            source = version_dir / name
            if not source.exists():
                mismatched.append(name)
                continue
            if _sha256_file(source) != expected:
                mismatched.append(name)
        if mismatched:
            return {"ok": False, "hashes": {}, "mismatched": mismatched}

    hashes = copy_candidate_to_active(version_dir, ml_dir=ml_dir, filenames=filenames)
    return {"ok": True, "hashes": hashes, "mismatched": []}


def copy_backtest_report_to_active(version_dir: Path, backtests_dir: Path) -> None:
    """Copies a promoted candidate's own strategy_report.json/equity_curves.csv
    over the active backtests/strategy_report.json/equity_curves.csv, so the
    live dashboard reflects the newly-active model's backtest instead of the
    now-archived one."""
    backtests_dir.mkdir(parents=True, exist_ok=True)
    for name in ("strategy_report.json", "equity_curves.csv"):
        source = version_dir / name
        if source.exists():
            shutil.copy2(source, backtests_dir / name)
