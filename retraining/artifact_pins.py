"""Pins of the installed model artifacts (V6.6.9, #382): one sha256 per file `main.py` loads.

The models, their schemas and the scaler are one set: a scaler refitted on other data leaves every file readable and
every input mis-scaled. Nothing compared them, so a rewritten `ml/scaler_stats.json` went unnoticed for as long as the
shipped book did not read the models. `ml/artifact_pins.json` records the set; anything that scores with the models
checks it first and refuses on a difference.

Stdlib only.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path

EXPERTS = ("bullish", "bearish", "sideways", "volatility")
# What `main.py` loads (its `_ensure_ready`), relative to `ml/`. A file that does not exist is not pinned.
PINNED_FILES: tuple[str, ...] = (
    "model_weights.json", "feature_schema.json", "scaler_stats.json",
    "multitask_model.json", "multitask_feature_schema.json",
    "sequence_model.json", "sequence_feature_schema.json",
    "gating_model.json", "gating_feature_schema.json",
    "topology_model.json", "topology_feature_schema.json",
    "rl_sizing_model.json",
    *(f"expert_models/{name}/{file}" for name in EXPERTS for file in ("model_weights.json", "multitask_model.json")),
)
NOTE = "sha256 of the installed model artifacts, one set (retraining/artifact_pins.py). Rewritten only by an install or a restore."


def file_sha256(path: Path) -> str:
    """The sha256 of a file's bytes."""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def compute_artifact_pins(ml_dir: Path | str, files: tuple[str, ...] = PINNED_FILES) -> dict[str, str]:
    """{relative path: sha256} of every pinned file that exists under `ml_dir`."""
    ml_dir = Path(ml_dir)
    return {name: file_sha256(ml_dir / name) for name in files if (ml_dir / name).is_file()}


def write_artifact_pins(ml_dir: Path | str, path: Path | str) -> dict[str, str]:
    """Record the current set at `path` (atomic, sorted, LF) and return it."""
    pins = compute_artifact_pins(ml_dir)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps({"note": NOTE, "files": pins}, indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    temporary.replace(path)
    return pins


def load_artifact_pins(path: Path | str) -> dict[str, str]:
    """The recorded set, or {} when there is no readable record."""
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    files = payload.get("files") if isinstance(payload, Mapping) else None
    return {str(name): str(digest) for name, digest in files.items()} if isinstance(files, Mapping) else {}


def check_artifact_pins(ml_dir: Path | str, pins: Mapping[str, str]) -> list[str]:
    """The pinned files that are missing or no longer match, sorted. [] is a healthy set; an empty record pins nothing,
    so a caller that requires a record must check for one itself (`artifact_problems`)."""
    ml_dir = Path(ml_dir)
    return sorted(name for name, digest in pins.items() if not (ml_dir / name).is_file() or file_sha256(ml_dir / name) != digest)


def snapshot_active(ml_dir: Path | str, destination: Path | str) -> Path:
    """Zip the active artifact set (every pinned file that exists, and the pin record) to `destination` before anything is retrained, so a
    retrain that stops half way can never leave the models without the scaler they were fitted with (#382)."""
    import zipfile

    ml_dir, destination = Path(ml_dir), Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    names = [*compute_artifact_pins(ml_dir), *(["artifact_pins.json"] if (ml_dir / "artifact_pins.json").is_file() else [])]
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in names:
            archive.write(ml_dir / name, f"ml/{name}")
    return destination


def artifact_problems(ml_dir: Path | str, pins_path: Path | str) -> list[str]:
    """Why the installed models may not be scored with, as messages: no record, or the files that differ from it."""
    pins = load_artifact_pins(pins_path)
    if not pins:
        return [f"no artifact pins at {Path(pins_path).name}"]
    return [f"{name} does not match its pin" for name in check_artifact_pins(ml_dir, pins)]
