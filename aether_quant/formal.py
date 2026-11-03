"""Differential cases computed by the Lean 4 models in formal/ (`aq prove --regen-cases`): run a Python function on a
case's `input` and compare with its `expected` to check it still matches the verified model."""

from __future__ import annotations

import hashlib
import json
from fractions import Fraction
from importlib import resources
from pathlib import Path

__all__ = ["cases_dir", "decode_rational", "load_cases", "spec_sha256", "targets", "to_float"]


def cases_dir() -> Path:
    return Path(str(resources.files("aether_quant") / "_formal_cases"))


def targets() -> list[str]:
    return sorted(path.stem for path in cases_dir().glob("*.json"))


def load_cases(target: str) -> dict:
    return json.loads((cases_dir() / f"{target}.json").read_text(encoding="utf-8"))


def decode_rational(value) -> Fraction | None:
    """`{"num": n, "den": d}` -> Fraction; JSON null -> None."""
    if value is None:
        return None
    return Fraction(int(value["num"]), int(value["den"]))


def to_float(value) -> float | None:
    fraction = decode_rational(value)
    return None if fraction is None else float(fraction)


def spec_sha256(spec_root: Path, spec_files: list[str]) -> str:
    """sha256 over the spec files' bytes in listed order (line endings normalised to LF)."""
    digest = hashlib.sha256()
    for name in spec_files:
        digest.update((spec_root / name).read_bytes().replace(b"\r\n", b"\n"))
    return digest.hexdigest()
