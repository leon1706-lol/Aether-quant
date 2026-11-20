"""retraining/model_catalog.py (V6.6.10): the example models' dataset, install, integrity checks, load and score; and the guard that
no example is one of the project's own models."""

from __future__ import annotations

import hashlib
import io
import json
import zipfile

import numpy as np
import pandas as pd
import pytest

from retraining import model_catalog as catalog


def _closes(sessions=200, names=6, seed=0):
    rng = np.random.default_rng(seed)
    index = [str(day.date()) for day in pd.bdate_range("2023-06-01", periods=sessions)]
    return pd.DataFrame(100 * np.exp(np.cumsum(rng.normal(0, 0.02, (sessions, names)), axis=0)), index=index, columns=[f"C{i}USD" for i in range(names)])


def _linear_multitask():
    return {"export": {"trunk": [{"type": "linear", "weight_key": "w", "bias_key": "b"}], "heads": {"rank_20d": [{"type": "linear", "weight_key": "h", "bias_key": "hb"}]},
                       "state_dict": {"w": [[1.0] * 6], "b": [0.0], "h": [[2.0]], "hb": [0.5]}}}


def _model_files():
    return {"multitask_model.json": json.dumps(_linear_multitask()).encode(), "multitask_feature_schema.json": json.dumps({"model_input_names": list(catalog.FEATURES)}).encode(),
            "card.md": b"# example"}


def _zip(path, files, *, manifest=True, tamper=None):
    listed = {name: hashlib.sha256(data).hexdigest() for name, data in files.items()}
    with zipfile.ZipFile(path, "w") as archive:
        for name, data in files.items():
            archive.writestr(name, tamper if (tamper and name == "multitask_model.json") else data)
        if manifest:
            archive.writestr("manifest.json", json.dumps({"files": listed}))
    return path


def test_features_use_only_the_past_and_are_standardised_per_date():
    closes = _closes()
    features = catalog.example_features(closes)
    later = closes.copy()
    later.iloc[-1] *= 3.0
    changed = catalog.example_features(later)
    last = closes.index[-1]
    pd.testing.assert_frame_equal(features[features["date"] < last].reset_index(drop=True), changed[changed["date"] < last].reset_index(drop=True))
    assert features.dropna().groupby("date")["ret_20"].mean().abs().max() < 1e-9
    assert catalog.example_features(closes.iloc[:, :1])[list(catalog.FEATURES)].isna().all().all(), "one name: no cross-section, no feature"


def test_the_dataset_has_every_split_and_target_the_trainers_read():
    frame = catalog.example_dataset(_closes(sessions=400), splits={"train_end": "2023-12-31", "validation_end": "2024-03-31", "backtest_end": "2024-06-30"})
    assert set(frame["split"]) == {"train", "validation", "backtest", "holdout"}
    for column in ("target_return_1d", "target_direction", "target_volatility_next_day", "target_rank_5d", "target_rank_20d", "target_direction_5d", "target_residual_rank_5d"):
        assert column in frame.columns
    assert frame[list(catalog.FEATURES)].notna().all().all() and frame["target_rank_20d"].dropna().between(0, 1).all()


def test_a_zip_is_checked_before_anything_is_unpacked(tmp_path):
    good = _zip(tmp_path / "good.zip", _model_files())
    assert catalog.zip_problems(good) == []
    assert catalog.zip_problems(_zip(tmp_path / "bare.zip", _model_files(), manifest=False)) == ["no manifest.json"]
    assert "sha256 differs" in catalog.zip_problems(_zip(tmp_path / "bad.zip", _model_files(), tamper=b"{}"))[0]
    with zipfile.ZipFile(tmp_path / "extra.zip", "w") as archive:
        archive.writestr("manifest.json", json.dumps({"files": {"gone.json": "00"}}))
        archive.writestr("stray.json", "{}")
    assert catalog.zip_problems(tmp_path / "extra.zip") == ["stray.json: not in the manifest", "gone.json: listed but missing"]
    with pytest.raises(ValueError, match="unknown example"):
        catalog.install_zip(good, name="nope", root=tmp_path / "cache")
    with pytest.raises(ValueError, match="release manifest"):
        catalog.install_zip(good, name="example-crypto-mlp", expected_sha256="0" * 64, root=tmp_path / "cache")
    with pytest.raises(ValueError, match="sha256 differs"):
        catalog.install_zip(tmp_path / "bad.zip", name="example-crypto-mlp", root=tmp_path / "cache")
    assert not (tmp_path / "cache" / "example-crypto-mlp").exists(), "a refusal leaves the cache as it was"
    folder = catalog.install_zip(good, name="example-crypto-mlp", expected_sha256=catalog.sha256_file(good), root=tmp_path / "cache")
    assert (folder / "multitask_model.json").exists() and catalog.install_zip(good, name="example-crypto-mlp", root=tmp_path / "cache") == folder


def test_install_downloads_the_manifest_then_the_zip(tmp_path):
    good = _zip(tmp_path / "good.zip", _model_files())
    manifest = {"models": {"example-crypto-mlp": {"sha256": catalog.sha256_file(good)}}}
    seen = []

    def opener(url, timeout):
        seen.append(url)
        return io.BytesIO(json.dumps(manifest).encode() if url.endswith(catalog.MANIFEST_ASSET) else good.read_bytes())

    folder = catalog.install("example-crypto-mlp", version="6.6.10", root=tmp_path / "cache", opener=opener)
    assert seen == [catalog.release_url(catalog.MANIFEST_ASSET, version="6.6.10"), catalog.release_url("example-crypto-mlp.zip", version="6.6.10")]
    assert "/download/v6.6.10/" in seen[0] and "/latest/download/" in catalog.release_url("x")
    assert catalog.load("example-crypto-mlp", root=tmp_path / "cache")["kind"] == "multitask" and folder.name == "example-crypto-mlp"
    with pytest.raises(ValueError, match="lists no"):
        catalog.install("example-crypto-seq", root=tmp_path / "cache", opener=opener)
    with pytest.raises(ValueError, match="unknown example"):
        catalog.install("nope", root=tmp_path / "cache", opener=opener)


def test_a_multitask_example_scores_every_row_with_the_numpy_pass(tmp_path):
    closes = _closes()
    model = catalog.load(catalog.install_zip(_zip(tmp_path / "m.zip", _model_files()), name="example-crypto-mlp", root=tmp_path))
    assert model["card"] == "# example" and [entry["name"] for entry in catalog.catalog()] == list(catalog.EXAMPLES)
    scores = catalog.score(model, closes)
    features = catalog.example_features(closes).dropna().set_index(["date", "ticker"])
    first = scores.iloc[0]
    assert len(scores) == len(features) and first["score"] == pytest.approx(2.0 * float(features.loc[(first["date"], first["ticker"])].sum()) + 0.5)
    with pytest.raises(FileNotFoundError, match="aq models install"):
        catalog.load(tmp_path / "empty")


def test_a_sequence_folder_scores_like_the_batched_forward_pass(tmp_path):
    torch = pytest.importorskip("torch")
    import train

    torch.manual_seed(0)
    network = train.AetherNetSequenceMultiTaskHorizons(input_dim=len(catalog.FEATURES), channels=[4], kernel_size=2, dropout=0.0)
    export = {"model": {"window_size": 5}, "export": train.export_sequence_multitask_horizons_architecture(network) | {"state_dict": train.export_state_dict(network)}}
    folder = tmp_path / "my_retrain"
    folder.mkdir()
    (folder / "sequence_model.json").write_text(json.dumps(export), encoding="utf-8")
    (folder / "sequence_feature_schema.json").write_text(json.dumps({"model_input_names": list(catalog.FEATURES), "window_size": 5}), encoding="utf-8")
    model = catalog.load(folder)
    scores = catalog.score(model, _closes(), head="rank_5d")
    assert model["kind"] == "sequence" and model["card"] == "" and scores["score"].notna().all() and np.isfinite(scores["score"].astype(float)).all()


def test_a_production_hash_is_never_published():
    files = _model_files()
    pinned = {"multitask_model.json": hashlib.sha256(files["multitask_model.json"]).hexdigest(), "scaler_stats.json": "ab" * 32}
    assert catalog.production_collisions(files, pinned) == ["multitask_model.json"]
    assert catalog.production_collisions(files, {}) == []
