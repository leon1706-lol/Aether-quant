"""json_safety.sanitize_json_finite against its Lean 4 model (formal/AetherFormal/JsonSafety.lean)."""

from __future__ import annotations

import math

import pytest

from aether_quant.formal import load_cases, to_float
from json_safety import sanitize_json_finite

NON_FINITE = {"nan": math.nan, "inf": math.inf, "-inf": -math.inf}


def _decode(node, *, as_tuple: bool = False):
    kind, value = node["t"], node.get("v")
    if kind == "null":
        return None
    if kind in ("bool", "int", "str"):
        return value
    if kind == "num":
        return to_float(value)
    if kind == "nonfinite":
        return NON_FINITE[value]
    if kind == "arr":
        items = [_decode(item, as_tuple=as_tuple) for item in value]
        return tuple(items) if as_tuple else items
    return {key: _decode(item, as_tuple=as_tuple) for key, item in value}


def _same(actual, expected) -> bool:
    if isinstance(expected, float):
        return isinstance(actual, float) and actual == pytest.approx(expected)
    if isinstance(expected, list):
        return isinstance(actual, list) and len(actual) == len(expected) and all(map(_same, actual, expected))
    if isinstance(expected, dict):
        return isinstance(actual, dict) and list(actual) == list(expected) and all(_same(actual[k], expected[k]) for k in expected)
    return actual == expected and type(actual) is type(expected)


def test_python_matches_the_lean_model():
    for index, case in enumerate(load_cases("json_safety")["cases"]):
        expected = _decode(case["expected"])
        assert _same(sanitize_json_finite(_decode(case["input"])), expected), index
        assert _same(sanitize_json_finite(_decode(case["input"], as_tuple=True)), expected), index
