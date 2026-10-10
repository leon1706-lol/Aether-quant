"""scripts/make_variant_configs.py: each retrain variant changes exactly its documented keys."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("make_variant_configs", ROOT / "scripts" / "make_variant_configs.py")
variants = importlib.util.module_from_spec(spec)
spec.loader.exec_module(variants)


def _flatten(value, prefix=()):
    if isinstance(value, dict):
        for key, item in value.items():
            yield from _flatten(item, prefix + (key,))
    else:
        yield prefix, value


def test_every_variant_differs_from_the_shipped_config_only_in_its_documented_keys():
    base = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    built = variants.build_variant_configs(base)

    assert set(built) == set(variants.VARIANTS)
    base_flat = dict(_flatten(base))
    for name, config in built.items():
        changed = {path for path, value in _flatten(config) if base_flat.get(path) != value}
        expected = {variants.MULTITASK_PATH + path for path, _ in variants.VARIANTS[name]}
        assert changed == expected, name
    assert base == json.loads((ROOT / "config.json").read_text(encoding="utf-8"))  # the base is never mutated


def test_the_same_variants_apply_to_the_sequence_model():
    base = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    built = variants.build_variant_configs(base, "sequence")
    for name, config in built.items():
        node = config["phase_v2"]["retraining"]["sequence_training"]
        control = base["phase_v2"]["retraining"]["sequence_training"]
        assert node != control, name
        assert config["phase_v2"]["retraining"]["multitask_training"] == base["phase_v2"]["retraining"]["multitask_training"]


def test_a_typo_in_a_variant_key_fails_loudly():
    base = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    with pytest.raises(KeyError):
        variants.apply_changes(base, [(("gate_aware_ranking_weights", "enabld"), False)])
    with pytest.raises(KeyError):
        variants.apply_changes(base, [(("no_such_block", "enabled"), False)])
