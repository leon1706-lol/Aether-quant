"""A lab model's configuration: what it reads, what it predicts, how it trains. `models/<name>/config.toml` merged over
`lab.toml` merged over `DEFAULTS`.
"""

from __future__ import annotations

import copy
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from lab.objectives import RANKING_OBJECTIVES

TEMPLATES = ("mlp", "multitask", "tcn", "linear")
TORCH_TEMPLATES = ("mlp", "multitask", "tcn")

DEFAULTS: dict[str, dict[str, Any]] = {
    "model": {"template": "multitask", "hidden": [64, 32], "dropout": 0.1, "channels": [32, 32], "kernel_size": 3, "window": 20, "ridge": 1.0},
    "data": {"dataset": "data/dataset.csv", "features": "all", "target": "target_rank_20d", "heads": ["rank_20d"]},
    "train": {"loss": "soft_spearman", "temperature": 0.1, "epochs": 30, "batch_dates": 16, "lr": 1e-3, "weight_decay": 1e-4, "optimizer": "adamw",
              "lr_schedule": "none", "patience": 5,
              "early_stop_smoothing_epochs": 1, "min_best_epoch": 0, "seeds": [7], "memory_profile": "standard", "device": "auto", "max_trials": 0},
    "eval": {"horizons": [5, 20], "cost_bps": 10.0, "top_n": 0, "min_names": 3},
}


def merge(base: Mapping[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    """`override` merged into `base`, nested tables key by key."""
    out = copy.deepcopy(dict(base))
    for key, value in override.items():
        out[key] = merge(out[key], value) if isinstance(value, Mapping) and isinstance(out.get(key), Mapping) else copy.deepcopy(value)
    return out


def read_toml(path: Path) -> dict[str, Any]:
    """A TOML file as a dict (Python 3.11 or newer: tomllib)."""
    if sys.version_info < (3, 11):
        raise ValueError("lab configs need Python 3.11 or newer (tomllib)")
    import tomllib  # novermin  (guarded above)

    return tomllib.loads(Path(path).read_text(encoding="utf-8"))


def validate(spec: Mapping[str, Any]) -> list[str]:
    """Every problem with a merged spec, as one line each (empty when it is usable)."""
    problems = []
    model, data, train = spec["model"], spec["data"], spec["train"]
    if model["template"] not in TEMPLATES:
        problems.append(f"model.template must be one of {', '.join(TEMPLATES)}, not {model['template']!r}")
    if train["loss"] not in RANKING_OBJECTIVES:
        problems.append(f"train.loss must be one of {', '.join(RANKING_OBJECTIVES)}, not {train['loss']!r}")
    if not isinstance(train["seeds"], list) or not train["seeds"] or not all(isinstance(seed, int) for seed in train["seeds"]):
        problems.append("train.seeds must be a non-empty list of integers")
    for key in ("epochs", "batch_dates", "patience"):
        if not isinstance(train[key], int) or train[key] < 1:
            problems.append(f"train.{key} must be a positive integer")
    if not data["target"].startswith("target_"):
        problems.append("data.target must name a target_* column, e.g. target_rank_20d")
    if train["memory_profile"] not in ("standard", "low"):
        problems.append("train.memory_profile must be standard or low")
    return problems


def load_spec(model_dir: Path, *, lab_dir: Path | None = None, overrides: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """DEFAULTS <- lab.toml <- models/<name>/config.toml <- overrides; raises ValueError listing every problem."""
    spec = copy.deepcopy(DEFAULTS)
    if lab_dir is not None and (lab_dir / "lab.toml").exists():
        spec = merge(spec, read_toml(lab_dir / "lab.toml"))
    if (model_dir / "config.toml").exists():
        spec = merge(spec, read_toml(model_dir / "config.toml"))
    spec = merge(spec, overrides or {})
    problems = validate(spec)
    if problems:
        raise ValueError("; ".join(problems))
    spec["model"]["name"] = model_dir.name
    return spec


def parse_override(text: str) -> dict[str, Any]:
    """'train.lr=3e-4' -> {'train': {'lr': 0.0003}}: the value parses as JSON, else stays a string."""
    import json

    key, _, raw = text.partition("=")
    if not key or not _:
        raise ValueError(f"bad override {text!r}: write section.key=value")
    try:
        value: Any = json.loads(raw)
    except ValueError:
        value = raw
    out: dict[str, Any] = {}
    node = out
    parts = key.strip().split(".")
    for part in parts[:-1]:
        node = node.setdefault(part, {})
    node[parts[-1]] = value
    return out
