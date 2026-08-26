"""Tests for json_safety.py (V5.4.7 - development/Problems.md #120).

Shared serialization/atomicity helpers: non-finite sanitization, numpy-scalar
tolerance, atomic writes, and lenient reads. Pure stdlib(+numpy) - no Redis,
no Postgres, no Lean.
"""

import json
from pathlib import Path

import pytest

from json_safety import (
    atomic_write_json,
    atomic_write_text,
    dumps_json_safe,
    load_json_lenient,
    sanitize_json_finite,
)


def test_sanitize_converts_non_finite_floats_to_none():
    payload = {"a": float("nan"), "b": float("inf"), "c": float("-inf"), "d": 1.5}
    clean = sanitize_json_finite(payload)
    assert clean == {"a": None, "b": None, "c": None, "d": 1.5}


def test_sanitize_handles_nested_containers_and_keeps_bools_ints_strings():
    payload = {
        "ok": True,
        "count": 3,
        "name": "AAPL",
        "nested": {"values": [float("nan"), 0.25], "flag": False},
        "empty": None,
    }
    clean = sanitize_json_finite(payload)
    assert clean["ok"] is True
    assert clean["count"] == 3
    assert clean["nested"]["values"] == [None, 0.25]
    assert clean["nested"]["flag"] is False


def test_sanitize_converts_numpy_scalars():
    np = pytest.importorskip("numpy")
    payload = {"vol": np.float64(0.12), "count": np.int64(7), "bad": np.float64("nan")}
    clean = sanitize_json_finite(payload)
    assert clean["vol"] == 0.12 and isinstance(clean["vol"], float)
    assert clean["count"] == 7 and isinstance(clean["count"], int)
    assert clean["bad"] is None


def test_dumps_json_safe_emits_strict_json_no_nan_literals():
    text = dumps_json_safe({"x": float("nan"), "y": [float("inf")]})
    # Strict parsers (PostgreSQL JSONB, browsers) reject bare NaN/Infinity.
    assert "NaN" not in text and "Infinity" not in text
    assert json.loads(text) == {"x": None, "y": [None]}


def test_atomic_write_json_round_trips(tmp_path: Path):
    target = tmp_path / "state.json"
    atomic_write_json(target, {"sharpe": 1.5, "nan_field": float("nan")}, indent=2)
    loaded = json.loads(target.read_text(encoding="utf-8"))
    assert loaded == {"sharpe": 1.5, "nan_field": None}
    # No temp files left behind.
    assert list(tmp_path.glob(".*tmp")) == []


def test_atomic_write_json_failure_preserves_previous_generation(tmp_path: Path):
    target = tmp_path / "state.json"
    atomic_write_json(target, {"generation": 1})
    class Unserializable:
        pass
    with pytest.raises(TypeError):
        atomic_write_json(target, {"generation": 2, "junk": Unserializable()})
    # The previous complete generation is intact - never torn.
    assert json.loads(target.read_text(encoding="utf-8")) == {"generation": 1}


def test_atomic_write_text_round_trips(tmp_path: Path):
    target = tmp_path / "cache.csv"
    atomic_write_text(target, "2026-01-02,4.5\n")
    assert target.read_text(encoding="utf-8") == "2026-01-02,4.5\n"


def test_load_json_lenient_degrades_to_none_on_any_failure(tmp_path: Path):
    missing = tmp_path / "missing.json"
    assert load_json_lenient(missing) is None

    torn = tmp_path / "torn.json"
    torn.write_text('{"partial": ', encoding="utf-8")
    assert load_json_lenient(torn) is None

    good = tmp_path / "good.json"
    good.write_text('{"ok": true}', encoding="utf-8")
    assert load_json_lenient(good) == {"ok": True}
