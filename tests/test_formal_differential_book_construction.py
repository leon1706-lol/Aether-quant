"""portfolio/book_construction.py against its Lean 4 model (formal/AetherFormal/BookConstruction.lean)."""

from __future__ import annotations

import pytest

from aether_quant.formal import load_cases, to_float
from portfolio.book_construction import (
    _select_book_group,
    apply_class_weight_caps,
    combine_tranche_weights,
    partial_adjust_weights,
    tranche_book_params,
)


def _book(values) -> dict[str, float]:
    return {f"N{i}": to_float(value) for i, value in enumerate(values) if to_float(value) != 0.0}


def _assert_weights(actual: dict[str, float], expected_values, index) -> None:
    for i, value in enumerate(expected_values):
        assert actual.get(f"N{i}", 0.0) == pytest.approx(to_float(value), abs=1e-12, rel=1e-9), (index, i)


def test_python_matches_the_lean_model():
    for index, case in enumerate(load_cases("book_construction")["cases"]):
        given, expected = case["input"], case["expected"]
        kind = case["kind"]
        if kind == "tranche_params":
            params = tranche_book_params(given["top_n"], given["bottom_n"], to_float(given["gross_exposure_cap"]), given["tranches"])
            assert (params["top_n"], params["bottom_n"]) == (expected["top_n"], expected["bottom_n"]), index
            assert params["gross_exposure_cap"] == pytest.approx(to_float(expected["gross_exposure_cap"])), index
        elif kind == "partial_adjust":
            out = partial_adjust_weights(_book(given["current"]), _book(given["target"]), to_float(given["fraction"]),
                                         to_float(given["min_weight"]))
            _assert_weights(out, expected["weights"], index)
        elif kind == "combine":
            out = combine_tranche_weights([_book(tranche) for tranche in given["tranches"]])
            _assert_weights(out, expected["weights"], index)
        elif kind == "class_caps":
            weights = {f"N{i}": to_float(value) for i, value in enumerate(given["weights"])}
            classes = {f"N{i}": ("crypto" if is_crypto else "equity") for i, is_crypto in enumerate(given["crypto"])}
            exempt = frozenset(f"N{i}" for i, flag in enumerate(given["exempt"]) if flag)
            caps = {"crypto": {"per_name_cap": to_float(given["per_name_cap"]),
                               "class_gross_cap": to_float(given["class_gross_cap"]), "exempt": exempt}}
            _assert_weights(apply_class_weight_caps(weights, classes, caps), expected["weights"], index)
        else:
            ranks = {f"N{i}": to_float(value) for i, value in enumerate(given["ranks"])}
            book = _select_book_group(ranks, given["top_n"], given["bottom_n"], min_rank_confidence_spread=-1e9)
            longs = [symbol for symbol, allocation in book.items() if allocation.role == "long"]
            shorts = [symbol for symbol, allocation in book.items() if allocation.role == "short"]
            assert longs == [f"N{i}" for i in expected["longs"]], index
            assert shorts == [f"N{i}" for i in expected["shorts"]], index
