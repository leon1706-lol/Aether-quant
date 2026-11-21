"""`aq lab export`: package a lab run in the `aq models` zip format, so `aq models install --from ZIP` and `aq models score`
work on it with the numpy forward pass (no torch).

The zip holds the exported network (`multitask_model.json`, `sequence_model.json` or `baseline_model.json`) or the linear
coefficients (`linear_model.json`), the feature schema, `lab_features.json` (which registry features, ranked within each
date, the model reads), the model card and a sha256 manifest, written with fixed entry times so the same run gives the same
bytes.
"""

from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path
from typing import Any

from lab import run_registry, trainer

FIXED_TIME = (2026, 1, 1, 0, 0, 0)
EXPORTABLE = ("multitask", "tcn", "mlp", "linear")


def write_zip(path: Path, files: dict[str, bytes]) -> str:
    """`files` plus a manifest of their sha256, with fixed entry times; returns the zip's sha256."""
    manifest = {"files": {name: hashlib.sha256(data).hexdigest() for name, data in sorted(files.items())}, "source": "lab"}
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in [*sorted(files.items()), ("manifest.json", json.dumps(manifest, indent=1, sort_keys=True).encode("utf-8"))]:
            archive.writestr(zipfile.ZipInfo(name, date_time=FIXED_TIME), data)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json(data: object) -> bytes:
    return json.dumps(data, indent=1, sort_keys=True).encode("utf-8")


def export_files(run_dir: Path, *, card: str) -> dict[str, bytes]:
    """{zip entry: bytes} for the run's first seed and last fold."""
    record = run_registry.read_run(run_dir)
    template = record["template"]
    if template not in EXPORTABLE:
        raise ValueError(f"export supports the {', '.join(EXPORTABLE)} templates, not {template!r}")
    features = list(record["features"])
    seed = record["seeds"][0]
    head = trainer.head_of(record["target"])
    files = {"lab_features.json": _json({"features": features, "inputs": "within-date percentile rank minus 0.5, missing = 0", "head": head}),
             "card.md": card.encode("utf-8")}
    if template == "linear":
        coefficients = json.loads(sorted(run_dir.glob(f"linear_*_seed_{seed}.json"))[-1].read_text(encoding="utf-8"))
        files["linear_model.json"] = _json({"kind": "linear", "head": head, "features": features, "coefficients": coefficients["coefficients"]})
        files["linear_feature_schema.json"] = _json({"model_input_names": features})
        return files
    torch = trainer.require_torch()
    from lab import architectures

    spec = json.loads((run_dir / "config.json").read_text(encoding="utf-8"))
    module = trainer.load_model_module(run_dir.parent.parent / "models" / record["model"])
    hparams = {key: value for key, value in spec["model"].items() if key not in {"template", "name"}}
    model = module.build(len(features), [head], **hparams)
    model.load_state_dict(torch.load(sorted(run_dir.glob(f"model_*_seed_{seed}.pt"))[-1], weights_only=True))
    model.eval()
    state = architectures.export_state_dict(model)
    if template == "tcn":
        window = int(spec["model"]["window"])
        files["sequence_model.json"] = _json({"model": {"type": "lab_sequence", "window_size": window, "model_input_features": features, "head": head},
                                              "export": architectures.export_sequence_multitask_horizons_architecture(model) | {"state_dict": state}})
        files["sequence_feature_schema.json"] = _json({"model_input_names": features, "window_size": window})
    elif template == "multitask":
        files["multitask_model.json"] = _json({"model": {"type": "lab_multitask", "model_input_features": features, "head": head},
                                               "export": architectures.export_multitask_horizons_architecture(model) | {"state_dict": state}})
        files["multitask_feature_schema.json"] = _json({"model_input_names": features})
    else:
        files["baseline_model.json"] = _json({"model": {"type": "lab_mlp", "model_input_features": features, "head": head},
                                              "export": {"architecture": architectures.export_architecture(model), "state_dict": state}})
        files["baseline_feature_schema.json"] = _json({"model_input_names": features})
    return files


def export_run(run_dir: Path, out: Path, *, card: str) -> dict[str, Any]:
    """A lab run as an `aq models` zip: the exported model, its feature schema and features, the card and a sha256 manifest."""
    files = export_files(run_dir, card=card)
    digest = write_zip(out, files)
    return {"zip": str(out), "sha256": digest, "files": sorted([*files, "manifest.json"])}
