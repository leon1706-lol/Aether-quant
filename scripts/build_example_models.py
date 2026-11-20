"""Builds the example models anyone can install (V6.6.10): two small networks trained on the library's bundled public sample only.

    python scripts/build_example_models.py --out dist/example_models

Writes `<name>.zip` for each example (the exported model, its schema, a model card and a manifest of their sha256) and
`example_models_manifest.json` (each zip's sha256 and size), the files the release job attaches. It reads the sample, the repo's
`config.json` (for the training defaults) and, under `ml/`, only the tracked `artifact_pins.json` (hashes) to refuse publishing an
installed model; the trainers write into a temporary folder.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from retraining import model_catalog as catalog  # noqa: E402

FIXED_TIME = (2026, 1, 1, 0, 0, 0)  # every zip entry carries this time, so the same files give the same zip
SMALL = {
    "epochs": 30, "patience": 6, "min_best_epoch": 3, "hidden_layers": [16], "batch_size": 64, "batch_mode": "random", "ranking_loss": None,
    "min_train_rows": 200, "min_validation_rows": 30, "min_backtest_rows": 30, "swa": {"enabled": False}, "seed": 0, "label_noise_std": 0.0,
    "gate_aware_ranking_weights": {"enabled": False},
}


def training_config(base: dict) -> dict:
    """The repo's config with the multitask and sequence trainers cut down to a small, seeded, plain run."""
    config = copy.deepcopy(base)
    retraining = config["phase_v2"]["retraining"]
    retraining["multitask_training"].update(SMALL)
    retraining["sequence_training"].update({**SMALL, "window_size": 20, "channels": [8, 8]})
    config["phase1"]["features"]["cross_sectional_inputs"] = {"enabled": False}
    config["phase1"]["target"]["ranking"]["net_performance"] = {"enabled": False}
    config["phase1"]["target"]["ranking"]["purged_cv"] = {"enabled": False}
    return config


def card(name: str, entry: dict, metrics: dict) -> str:
    backtest = metrics.get("backtest", {}).get("rank_20d_ic") or {}
    return (
        f"# {name}\n\n{entry['summary']}\n\n"
        "An example, not a trading model: it shows the format, the forward pass and `aq models score`. The project's own models are not published.\n\n"
        f"- Data: the 11 coins of `aether_quant/_sample/coinbase_daily.csv.gz` (Coinbase public daily candles), train to {catalog.SPLITS['train_end']}, "
        f"validation to {catalog.SPLITS['validation_end']}, backtest to {catalog.SPLITS['backtest_end']}.\n"
        f"- Inputs: {', '.join(catalog.FEATURES)}, each z-scored across the coins of its date.\n"
        f"- Backtest rank IC (20 sessions): {backtest.get('mean_ic')}\n"
    )


def write_zip(path: Path, files: dict[str, bytes]) -> str:
    """The zip of `files` plus a manifest of their sha256, with fixed entry times; returns its sha256."""
    manifest = {"files": {name: hashlib.sha256(data).hexdigest() for name, data in sorted(files.items())}}
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in [*sorted(files.items()), ("manifest.json", json.dumps(manifest, indent=1, sort_keys=True).encode("utf-8"))]:
            archive.writestr(zipfile.ZipInfo(name, date_time=FIXED_TIME), data)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def train(kind: str, *, work: Path, config_path: Path, dataset: Path, schema: Path) -> Path:
    """Runs one trainer's `main()` in this process with its model folder moved into `work`, so nothing lands in the repo's `ml/`."""
    import train_multitask
    import train_sequence

    module = train_sequence if kind == "sequence" else train_multitask
    ml_dir, argv = module.ML_DIR, sys.argv
    module.ML_DIR = work / "ml"
    sys.argv = [module.__name__, "--version-id", kind, "--config-path", str(config_path), "--dataset-path", str(dataset), "--feature-schema-path", str(schema),
                "--memory-profile", "low"]
    try:
        if module.main() != 0:
            raise RuntimeError(f"the {kind} trainer failed")
    finally:
        # Restored: a later in-process trainer would otherwise write into this (deleted) work folder
        module.ML_DIR, sys.argv = ml_dir, argv
    return work / "ml" / "versions" / kind


def build(out: Path, *, work: Path) -> dict:
    from aether_quant.samples import load_sample_prices

    frame = catalog.example_dataset(load_sample_prices())
    dataset = work / "dataset.csv"
    frame.to_csv(dataset, index=False)
    schema = work / "feature_schema.json"
    schema.write_text(json.dumps({"model_input_names": list(catalog.FEATURES), "feature_names": list(catalog.FEATURES)}), encoding="utf-8")
    config_path = work / "config.json"
    config_path.write_text(json.dumps(training_config(json.loads((ROOT / "config.json").read_text(encoding="utf-8")))), encoding="utf-8")
    manifest: dict = {"models": {}}
    pins = ROOT / "ml" / "artifact_pins.json"  # tracked: hashes only, read to refuse publishing an installed model
    pinned = json.loads(pins.read_text(encoding="utf-8")).get("files", {}) if pins.exists() else {}
    for name, entry in catalog.EXAMPLES.items():
        version = train(entry["kind"], work=work, config_path=config_path, dataset=dataset, schema=schema)
        metrics_name = "sequence_training_metrics.json" if entry["kind"] == "sequence" else "multitask_training_metrics.json"
        metrics = json.loads((version / metrics_name).read_text(encoding="utf-8"))
        files = {entry["model"]: (version / entry["model"]).read_bytes(), entry["schema"]: (version / entry["schema"]).read_bytes(),
                 "card.md": card(name, entry, metrics).encode("utf-8")}
        collisions = catalog.production_collisions(files, pinned)
        if collisions:
            raise RuntimeError(f"{name}: {collisions} match an installed model's pinned hash; a production model is never published")
        sha = write_zip(out / f"{name}.zip", files)
        manifest["models"][name] = {"sha256": sha, "size": (out / f"{name}.zip").stat().st_size, "kind": entry["kind"]}
    (out / catalog.MANIFEST_ASSET).write_text(json.dumps(manifest, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", default="dist/example_models")
    args = parser.parse_args(argv)
    out = Path(args.out) if Path(args.out).is_absolute() else ROOT / args.out
    with tempfile.TemporaryDirectory(prefix="aq_examples_") as work:
        manifest = build(out, work=Path(work))
    print(json.dumps(manifest, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
