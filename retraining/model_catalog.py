"""Example models anyone can install (V6.6.10): small networks trained on the library's bundled public sample, published as
GitHub release assets, installed into a local cache and scored with the numpy forward pass (no torch).

The project's own trading models are never among them: they stay on the owner's machine. `scripts/build_example_models.py`
trains the examples from `aether_quant/_sample/` alone, and a test checks that no example file shares a name or a hash with
an installed model (`ml/artifact_pins.json`).

Trust: the release job builds the zips and a manifest of their sha256 in one run and signs the release's files (Sigstore).
`install` downloads the manifest over HTTPS, refuses a zip whose hash differs, and checks every file inside against the zip's
own manifest before anything is read.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import urllib.request
import zipfile
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

REPOSITORY = "leon1706-lol/Aether-quant"
MANIFEST_ASSET = "example_models_manifest.json"
DEFAULT_ROOT = Path.home() / ".cache" / "aether-quant" / "models"
FEATURES = ("ret_1", "ret_5", "ret_20", "ret_60", "vol_20", "vol_60")
SPLITS = {"train_end": "2023-12-31", "validation_end": "2024-12-31", "backtest_end": "2025-12-31"}
EXAMPLES: dict[str, dict[str, str]] = {
    "example-crypto-mlp": {
        "kind": "multitask", "model": "multitask_model.json", "schema": "multitask_feature_schema.json",
        "summary": "A small multitask network on six return and volatility features of the 11 sample coins.",
    },
    "example-crypto-seq": {
        "kind": "sequence", "model": "sequence_model.json", "schema": "sequence_feature_schema.json",
        "summary": "A small causal convolutional network over 20 sessions of the same six features.",
    },
}


def catalog() -> list[dict[str, str]]:
    """The example models, by name: what each is and which file holds it."""
    return [{"name": name, **entry} for name, entry in EXAMPLES.items()]


def example_features(closes: pd.DataFrame) -> pd.DataFrame:
    """Long rows (date, ticker, features) from a dates x tickers close table. Each feature uses closes up to its own date only, and is
    z-scored across the tickers of that date (a date with fewer than two names, or no spread, is NaN)."""
    returns = closes.pct_change(fill_method=None)
    raw = {
        "ret_1": returns, "ret_5": closes.pct_change(5, fill_method=None), "ret_20": closes.pct_change(20, fill_method=None),
        "ret_60": closes.pct_change(60, fill_method=None), "vol_20": returns.rolling(20, min_periods=20).std(), "vol_60": returns.rolling(60, min_periods=60).std(),
    }
    columns = {}
    for name, table in raw.items():
        spread = table.std(axis=1, ddof=0)
        columns[name] = table.sub(table.mean(axis=1), axis=0).div(spread.where(spread > 0), axis=0).where(table.notna().sum(axis=1) >= 2, axis=0)
    long = pd.concat({name: table.stack(future_stack=True) for name, table in columns.items()}, axis=1)
    long.index.names = ["date", "ticker"]
    return long.reset_index().astype({"date": str, "ticker": str})


def example_dataset(closes: pd.DataFrame, *, splits: Mapping[str, str] = SPLITS) -> pd.DataFrame:
    """The trainers' dataset format from a close table: the features, every target the heads read (forward returns and their daily
    ranks), a split by date and the bookkeeping columns. Rows without every feature are dropped; the last rows keep NaN targets."""
    frame = example_features(closes)
    forward = {h: (closes.shift(-h) / closes - 1.0) for h in (1, 5, 20)}
    ranks = {h: forward[h].rank(axis=1, pct=True) for h in (5, 20)}
    volatility = forward[1].abs()

    def column(table: pd.DataFrame) -> np.ndarray:
        return table.stack(future_stack=True).reindex(pd.MultiIndex.from_frame(frame[["date", "ticker"]])).to_numpy(dtype=float)

    frame["target_return_1d"] = column(forward[1])
    frame["target_direction"] = (frame["target_return_1d"] > 0).astype(float).where(frame["target_return_1d"].notna())
    frame["target_volatility_next_day"] = column(volatility)
    frame["target_return_5d"], frame["target_return_20d"] = column(forward[5]), column(forward[20])
    frame["target_direction_5d"] = (frame["target_return_5d"] > 0).astype(float).where(frame["target_return_5d"].notna())
    frame["target_direction_20d"] = (frame["target_return_20d"] > 0).astype(float).where(frame["target_return_20d"].notna())
    frame["target_rank_5d"], frame["target_rank_20d"] = column(ranks[5]), column(ranks[20])
    for name in ("target_sector_neutral_rank_20d", "target_beta_neutral_rank_20d", "target_residual_rank_20d"):
        frame[name] = frame["target_rank_20d"]
    frame["target_residual_rank_5d"] = frame["target_rank_5d"]
    frame = frame.dropna(subset=list(FEATURES) + ["target_return_1d", "target_volatility_next_day"]).reset_index(drop=True)
    frame["split"] = np.select(
        [frame["date"] <= splits["train_end"], frame["date"] <= splits["validation_end"], frame["date"] <= splits["backtest_end"]],
        ["train", "validation", "backtest"], "holdout",
    )
    frame["training_eligible"] = True
    frame["security_type"] = "crypto"
    return frame.sort_values(["ticker", "date"]).reset_index(drop=True)


def production_collisions(files: Mapping[str, bytes], pinned: Mapping[str, str]) -> list[str]:
    """The example files whose sha256 is one of the installed models' pinned hashes (`ml/artifact_pins.json` "files"): a production model
    must never be published as an example, so the build refuses any."""
    hashes = set(pinned.values())
    return sorted(name for name, data in files.items() if hashlib.sha256(data).hexdigest() in hashes)


def release_url(asset: str, *, version: str | None = None) -> str:
    """The download URL of a release asset: the latest release, or the tag `v<version>`."""
    base = f"https://github.com/{REPOSITORY}/releases"
    return f"{base}/latest/download/{asset}" if version is None else f"{base}/download/v{version}/{asset}"


def sha256_file(path: Path) -> str:
    """The file's sha256, read in chunks: what a release manifest lists for each published file."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def zip_problems(path: Path) -> list[str]:
    """What is wrong inside an example zip: a missing manifest, a file the manifest does not list, or a file whose hash differs."""
    problems = []
    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())
        if "manifest.json" not in names:
            return ["no manifest.json"]
        listed = json.loads(archive.read("manifest.json")).get("files", {})
        for name in sorted(names - {"manifest.json"}):
            if name not in listed:
                problems.append(f"{name}: not in the manifest")
            elif hashlib.sha256(archive.read(name)).hexdigest() != listed[name]:
                problems.append(f"{name}: sha256 differs from the manifest")
        problems.extend(f"{name}: listed but missing" for name in sorted(set(listed) - names))
    return problems


def install_zip(path: Path, *, name: str, expected_sha256: str | None = None, root: Path | None = None) -> Path:
    """Checks a downloaded (or local) example zip and unpacks it into `root/<name>/`. Refuses an unknown name, a hash that differs
    from `expected_sha256`, or any problem inside; a refusal leaves the cache as it was."""
    if name not in EXAMPLES:
        raise ValueError(f"unknown example model {name!r}; expected one of {sorted(EXAMPLES)}")
    if expected_sha256 is not None and sha256_file(path) != expected_sha256:
        raise ValueError(f"{Path(path).name}: sha256 differs from the release manifest; refusing it")
    problems = zip_problems(path)
    if problems:
        raise ValueError(f"{Path(path).name}: {'; '.join(problems)}")
    target = Path(root or DEFAULT_ROOT) / name
    staging = target.with_name(f".{name}.partial")
    shutil.rmtree(staging, ignore_errors=True)
    with zipfile.ZipFile(path) as archive:
        archive.extractall(staging)
    shutil.rmtree(target, ignore_errors=True)
    staging.rename(target)
    return target


def _download(url: str, destination: Path, *, opener: Callable[..., Any] = urllib.request.urlopen) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with opener(url, timeout=60) as response, destination.open("wb") as handle:
        shutil.copyfileobj(response, handle)
    return destination


def install(name: str, *, version: str | None = None, root: Path | None = None, opener: Callable[..., Any] = urllib.request.urlopen) -> Path:
    """Downloads `name` from the release (the latest, or `v<version>`), checks it against the release manifest and unpacks it.
    Returns the model's folder."""
    if name not in EXAMPLES:
        raise ValueError(f"unknown example model {name!r}; expected one of {sorted(EXAMPLES)}")
    folder = Path(root or DEFAULT_ROOT)
    manifest = json.loads(_download(release_url(MANIFEST_ASSET, version=version), folder / ".downloads" / MANIFEST_ASSET, opener=opener).read_text(encoding="utf-8"))
    entry = manifest.get("models", {}).get(name)
    if not entry:
        raise ValueError(f"the release manifest lists no {name!r}")
    zip_path = _download(release_url(f"{name}.zip", version=version), folder / ".downloads" / f"{name}.zip", opener=opener)
    return install_zip(zip_path, name=name, expected_sha256=entry["sha256"], root=folder)


def load(name_or_path: str | Path, *, root: Path | None = None) -> dict[str, Any]:
    """An installed example (by name) or any folder holding one exported model and its schema (your own `ml/versions/<id>/`, say):
    {"name", "kind", "export", "schema", "card"}."""
    folder = Path(name_or_path)
    if str(name_or_path) in EXAMPLES:
        folder = Path(root or DEFAULT_ROOT) / str(name_or_path)
    for kind, model_file, schema_file in (("sequence", "sequence_model.json", "sequence_feature_schema.json"), ("multitask", "multitask_model.json", "multitask_feature_schema.json")):
        if (folder / model_file).exists():
            card = folder / "card.md"
            return {
                "name": folder.name, "kind": kind, "export": json.loads((folder / model_file).read_text(encoding="utf-8")),
                "schema": json.loads((folder / schema_file).read_text(encoding="utf-8")), "card": card.read_text(encoding="utf-8") if card.exists() else "",
            }
    raise FileNotFoundError(f"no exported model in {folder} (install it first: aq models install <name>)")


def score(model: Mapping[str, Any], closes: pd.DataFrame, *, head: str = "rank_20d") -> pd.DataFrame:
    """One model's `head` for every (date, ticker) the close table has every feature for, as long rows (date, ticker, score). The inputs
    are `example_features(closes)` in the schema's order; a sequence model reads each ticker's last `window_size` rows, zero-padded."""
    from inference import run_exported_multitask_model, run_exported_sequence_multitask_model_batched
    from retraining.slicing import gather_windows, sequence_window_index

    names = list(model["schema"]["model_input_names"])
    frame = example_features(closes).dropna(subset=names).sort_values(["ticker", "date"]).reset_index(drop=True)
    matrix = frame[names].to_numpy(dtype=np.float64)
    if model["kind"] == "sequence":
        window = int(model["schema"].get("window_size") or model["export"]["model"]["window_size"])
        sequences = gather_windows(matrix, sequence_window_index(frame["ticker"].to_numpy(), window)).tolist()
        outputs = run_exported_sequence_multitask_model_batched(model["export"], sequences)
    else:
        outputs = [run_exported_multitask_model(model["export"], list(row)) for row in matrix]
    frame["score"] = [None if output is None else output.get(head) for output in outputs]
    return frame[["date", "ticker", "score"]].sort_values(["date", "ticker"]).reset_index(drop=True)
