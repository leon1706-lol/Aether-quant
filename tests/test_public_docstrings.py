"""Every function and class `aether_quant` exports is documented and fully annotated (V6.6.5, #346), so the API reference
(docs/reference/, mkdocstrings) has something to say about each one and a type checker sees no Unknown."""

from __future__ import annotations

import importlib
import importlib.util
import inspect
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _exports():
    seen = set()
    for path in sorted((ROOT / "aether_quant").glob("*.py")):
        if path.stem.startswith("_"):
            continue
        module = importlib.import_module(f"aether_quant.{path.stem}")
        for name in module.__all__:
            obj = getattr(module, name)
            if (inspect.isfunction(obj) or inspect.isclass(obj)) and id(obj) not in seen:
                seen.add(id(obj))
                yield f"{obj.__module__}.{obj.__qualname__}", obj


def test_every_exported_function_and_class_has_a_docstring():
    missing = []
    for name, obj in _exports():
        doc = obj.__doc__ if inspect.isfunction(obj) else (vars(obj).get("__doc__") or "")
        if inspect.isclass(obj) and doc.startswith(obj.__name__ + "("):
            doc = ""  # the signature dataclasses write when a class has no docstring of its own
        if not (doc or "").strip():
            missing.append(name)
    assert not missing, f"document these exports: {missing}"


def test_type_completeness_never_falls():
    spec = importlib.util.spec_from_file_location("type_completeness", ROOT / "scripts" / "type_completeness.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["type_completeness"] = module
    spec.loader.exec_module(module)
    result = module.measure()
    floor = __import__("json").loads((ROOT / "tests" / "data" / "type_completeness_floor.json").read_text(encoding="utf-8"))
    assert result["score"] >= floor["floor"]
    assert set(result["incomplete"]) <= set(floor["incomplete"]), sorted(set(result["incomplete"]) - set(floor["incomplete"]))
    assert result["total"] > 800
