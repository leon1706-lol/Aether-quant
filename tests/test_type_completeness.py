"""scripts/type_completeness.py (V6.6.6): what counts as an unannotated or bare-typed exported callable, and the floor that only rises."""

from __future__ import annotations

import dataclasses
import json
import typing

from script_loader import load_script


def test_a_function_needs_every_parameter_and_the_return_typed(monkeypatch):
    module = load_script("type_completeness")

    def complete(x: int, *, y: "list[int]" = None) -> int: ...  # noqa: E704

    def bare(x: dict, y) -> list: ...  # noqa: E704

    def no_return(x: int): ...  # noqa: E704

    assert module._problems_of_function(complete) == []
    assert module._problems_of_function(bare) == ["parameter x is a bare dict", "parameter y has no annotation", "return is a bare list"]
    assert module._problems_of_function(no_return) == ["no return annotation"]
    monkeypatch.setattr(module.inspect, "signature", lambda function: (_ for _ in ()).throw(ValueError("no signature")))
    assert module._problems_of_function(bare) == [], "an object without a signature has nothing to annotate"
    assert module._annotation_text("typing.List") == "typing.List" and module._annotation_text(typing.Any) in ("Any", "typing.Any")


def test_a_class_is_judged_on_its_public_members_and_its_own_init():
    module = load_script("type_completeness")

    class Plain:
        def __init__(self, x):
            self.x = x

        def method(self, y: int) -> int:
            return y

        @property
        def size(self):
            return 1

        @classmethod
        def build(cls, z) -> "Plain":
            return cls(z)

        def _private(self, q): ...  # noqa: E704

    @dataclasses.dataclass
    class Generated:
        value: int

    class Proto(typing.Protocol):
        def __init__(self, a): ...  # noqa: E704

    assert module._problems_of_class(Plain) == ["__init__: parameter x has no annotation", "__init__: no return annotation", "size: no return annotation", "build: parameter z has no annotation"]
    assert module._problems_of_class(Generated) == [] and module._problems_of_class(Proto) == []


def test_the_measure_counts_each_exported_callable_once():
    module = load_script("type_completeness")
    result = module.measure()
    assert result["total"] > 100 and 0.0 <= result["score"] <= 1.0 and result["complete"] == result["total"] - len(result["incomplete"])
    assert module.facade_modules() and all(not name.startswith("_") for name in module.facade_modules())


def test_the_gate_compares_with_the_floor_and_can_move_it(tmp_path, monkeypatch, capsys):
    module = load_script("type_completeness")
    floor = tmp_path / "floor.json"
    monkeypatch.setattr(module, "FLOOR", floor)
    state = {"score": 0.9, "complete": 9, "total": 10, "incomplete": {"a.f": ["no return annotation"]}}
    monkeypatch.setattr(module, "measure", lambda: state)
    report = tmp_path / "report.json"
    assert module.main(["--report", str(report)]) == 1 and json.loads(report.read_text(encoding="utf-8"))["total"] == 10  # no floor file: every incomplete name is new
    assert module.main(["--update-floor"]) == 0 and json.loads(floor.read_text(encoding="utf-8"))["floor"] == 0.9
    assert "floor set to 90.0% with 1 names still incomplete" in capsys.readouterr().out
    assert module.main([]) == 0
    state.update(score=0.8, incomplete={"a.f": ["x"], "a.g": ["parameter y has no annotation"]})
    assert module.main([]) == 1
    err = capsys.readouterr().err
    assert "fell below the floor" in err and "a.g: parameter y has no annotation" in err
    state.update(score=1.0, incomplete={})
    assert module.main([]) == 0 and "now complete" in capsys.readouterr().out


def test_a_non_callable_or_repeated_or_missing_export_is_not_counted_twice(monkeypatch):
    import sys
    import types

    module = load_script("type_completeness")

    def annotated(value: int) -> int:
        return value

    fake = types.ModuleType("aether_quant.fake_facade")
    def bare(value):
        return value

    fake.__all__ = ["CONSTANT", "annotated", "annotated_again", "missing", "bare"]
    fake.bare = bare
    fake.CONSTANT = 3
    fake.annotated = annotated
    fake.annotated_again = annotated
    monkeypatch.setitem(sys.modules, "aether_quant.fake_facade", fake)
    monkeypatch.setattr(module, "facade_modules", lambda: ["fake_facade"])
    result = module.measure()
    assert result["total"] == 2 and result["complete"] == 1 and result["score"] == 0.5 and len(result["incomplete"]) == 1 and next(iter(result["incomplete"])).endswith("bare")


def test_the_script_run_as_main_reports_its_usage(monkeypatch, capsys):
    from script_loader import run_script

    assert run_script("type_completeness", ["--help"], monkeypatch) == 0 and "--update-floor" in capsys.readouterr().out
