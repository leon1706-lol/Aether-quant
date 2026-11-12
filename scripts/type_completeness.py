"""Type completeness of the public library (V6.6.5, #346): every callable `aether_quant` exports, fully annotated.

A callable counts as complete when every parameter (bar `self`/`cls`) and its return carry an annotation and none of them
is a bare container (`dict`, `list`, `tuple`, `set`, `Mapping`, `Sequence`, `Callable`, ... without parameters), which a
type checker reads as "of Unknown". A class counts through its public methods (and an explicit `__init__`); dataclass
fields are annotated by construction. Imports nothing heavy: the facades load as the lite install does.

The score may only rise: `tests/data/type_completeness_floor.json` holds the floor and the names still incomplete, and
this exits 1 when the score falls below the floor or a new incomplete name appears.

    python scripts/type_completeness.py                  # check against the floor
    python scripts/type_completeness.py --report FILE    # also write every incomplete name and why
    python scripts/type_completeness.py --update-floor   # after a fix: raise the floor, shrink the list
"""

from __future__ import annotations

import argparse
import dataclasses
import importlib
import inspect
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
FLOOR = ROOT / "tests" / "data" / "type_completeness_floor.json"
BARE = re.compile(r"^(typing\.)?(dict|list|tuple|set|frozenset|Dict|List|Tuple|Set|FrozenSet|Mapping|MutableMapping|Sequence|Iterable|Iterator|Callable)$")


def facade_modules() -> list[str]:
    return sorted(path.stem for path in (ROOT / "aether_quant").glob("*.py") if not path.stem.startswith("_"))


def _annotation_text(annotation: object) -> str:
    if annotation is inspect.Parameter.empty:
        return ""
    return annotation if isinstance(annotation, str) else getattr(annotation, "__name__", None) or str(annotation)


def _problems_of_function(function: object) -> list[str]:
    try:
        signature = inspect.signature(function)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return []  # a C builtin or an object without a signature: nothing to annotate
    problems = []
    for name, parameter in signature.parameters.items():
        if name in ("self", "cls"):
            continue
        text = _annotation_text(parameter.annotation).strip()
        if not text:
            problems.append(f"parameter {name} has no annotation")
        elif BARE.match(text.replace(" ", "")):
            problems.append(f"parameter {name} is a bare {text}")
    returned = _annotation_text(signature.return_annotation).strip()
    if not returned:
        problems.append("no return annotation")
    elif BARE.match(returned.replace(" ", "")):
        problems.append(f"return is a bare {returned}")
    return problems


def _problems_of_class(cls: type) -> list[str]:
    problems = []
    # a dataclass's __init__ is generated from its annotated fields; a Protocol's is typing's placeholder
    generated_init = dataclasses.is_dataclass(cls) or bool(getattr(cls, "_is_protocol", False))
    for name, member in vars(cls).items():
        if name.startswith("_") and not (name == "__init__" and not generated_init):
            continue
        target = member.__func__ if isinstance(member, (classmethod, staticmethod)) else member
        if isinstance(target, property):
            target = target.fget
        if inspect.isfunction(target):
            problems += [f"{name}: {problem}" for problem in _problems_of_function(target)]
    return problems


def measure() -> dict[str, object]:
    """{"score", "complete", "total", "incomplete": {qualified name: [problems]}}, over every exported callable."""
    seen: dict[int, str] = {}
    incomplete: dict[str, list[str]] = {}
    total = 0
    for module_name in facade_modules():
        module = importlib.import_module(f"aether_quant.{module_name}")
        for name in getattr(module, "__all__", []):
            obj = getattr(module, name, None)
            if obj is None or not (inspect.isfunction(obj) or inspect.isclass(obj)) or id(obj) in seen:
                continue
            qualified = f"{getattr(obj, '__module__', '?')}.{getattr(obj, '__qualname__', name)}"
            seen[id(obj)] = qualified
            total += 1
            problems = _problems_of_class(obj) if inspect.isclass(obj) else _problems_of_function(obj)
            if problems:
                incomplete[qualified] = problems
    complete = total - len(incomplete)
    return {"score": round(complete / total, 4) if total else 1.0, "complete": complete, "total": total, "incomplete": dict(sorted(incomplete.items()))}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--report", default=None, metavar="FILE")
    parser.add_argument("--update-floor", action="store_true")
    args = parser.parse_args(argv)
    result = measure()
    print(f"type completeness: {result['complete']}/{result['total']} exported callables fully annotated ({float(result['score']):.1%})")
    if args.report:
        Path(args.report).write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8")
    if args.update_floor:
        FLOOR.write_text(json.dumps({"floor": result["score"], "incomplete": sorted(result["incomplete"])}, indent=1) + "\n", encoding="utf-8", newline="\n")
        print(f"floor set to {float(result['score']):.1%} with {len(result['incomplete'])} names still incomplete")
        return 0
    floor = json.loads(FLOOR.read_text(encoding="utf-8")) if FLOOR.exists() else {"floor": 0.0, "incomplete": []}
    problems = []
    if float(result["score"]) < float(floor["floor"]):
        problems.append(f"score {float(result['score']):.1%} fell below the floor {float(floor['floor']):.1%}")
    new = sorted(set(result["incomplete"]) - set(floor["incomplete"]))
    problems += [f"{name}: {'; '.join(result['incomplete'][name])}" for name in new]  # type: ignore[index]
    fixed = sorted(set(floor["incomplete"]) - set(result["incomplete"]))
    if fixed:
        print(f"{len(fixed)} name(s) now complete: run with --update-floor to lock the gain")
    for problem in problems:
        print(f"type completeness: {problem}", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
