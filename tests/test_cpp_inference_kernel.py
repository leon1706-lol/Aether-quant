"""The C++ kernel `cpp_inference.linear_batched` against NumPy's einsum (V6.6.8, #380).

CI's cpp-sanitizers job builds the extension with AddressSanitizer and UBSan and runs this file under them, with
AQ_REQUIRE_CPP_INFERENCE=1 so a missing build fails instead of skipping. hypothesis drives random shapes (zero sizes
included), dtypes, layouts and non-finite values through the kernel, so an out-of-bounds read or undefined behaviour
aborts the job. Where the extension is not built (the PC, the other CI jobs), the file skips.
"""

from __future__ import annotations

import importlib
import os

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from hypothesis.extra import numpy as hnp

REQUIRED = os.environ.get("AQ_REQUIRE_CPP_INFERENCE") == "1"
cpp = importlib.import_module("cpp_inference") if REQUIRED else pytest.importorskip("cpp_inference")


def reference(weights, inputs, bias):
    return np.einsum("noi,ni->no", np.asarray(weights, dtype=np.float64), np.asarray(inputs, dtype=np.float64)) + np.asarray(bias, dtype=np.float64)


@st.composite
def kernel_inputs(draw, elements=None):
    n, out, inp = draw(st.integers(0, 6)), draw(st.integers(0, 6)), draw(st.integers(0, 6))
    values = elements if elements is not None else st.floats(-1e6, 1e6, allow_nan=False, width=64)
    weights = draw(hnp.arrays(np.float64, (n, out, inp), elements=values))
    inputs = draw(hnp.arrays(np.float64, (n, inp), elements=values))
    bias = draw(hnp.arrays(np.float64, (n, out), elements=values))
    return weights, inputs, bias


@pytest.mark.skipif(not REQUIRED, reason="only the cpp-sanitizers job requires the build")
def test_the_required_build_is_the_one_exported_model_uses():
    from inference import exported_model

    assert exported_model._cpp_inference is not None
    assert exported_model._cpp_inference.linear_batched is cpp.linear_batched


@settings(max_examples=400, deadline=None)
@given(kernel_inputs())
def test_the_kernel_matches_einsum_on_finite_inputs(case):
    weights, inputs, bias = case
    result = cpp.linear_batched(weights, inputs, bias)

    assert result.shape == (weights.shape[0], weights.shape[1]) and result.dtype == np.float64
    np.testing.assert_allclose(result, reference(weights, inputs, bias), rtol=1e-9, atol=1e-6)


# finite values stay small, so no sum overflows: then whether a cell is NaN or +-inf does not depend on summation order
NON_FINITE = st.one_of(st.floats(-1e6, 1e6, width=64), st.sampled_from([np.nan, np.inf, -np.inf]))


@settings(max_examples=200, deadline=None)
@given(kernel_inputs(elements=NON_FINITE))
def test_non_finite_values_land_where_einsum_puts_them(case):
    weights, inputs, bias = case
    with np.errstate(all="ignore"):
        result = cpp.linear_batched(weights, inputs, bias)
        expected = reference(weights, inputs, bias)

    np.testing.assert_array_equal(np.isnan(result), np.isnan(expected))
    np.testing.assert_array_equal(np.isposinf(result), np.isposinf(expected))
    np.testing.assert_array_equal(np.isneginf(result), np.isneginf(expected))
    finite = np.isfinite(expected)
    np.testing.assert_allclose(result[finite], expected[finite], rtol=1e-9, atol=1e-6)


def test_other_dtypes_and_layouts_are_cast_and_copied_first():
    rng = np.random.default_rng(7)
    wide = rng.normal(size=(3, 8, 5))
    weights = wide[:, ::2, :]  # a strided view
    inputs = np.asfortranarray(rng.normal(size=(3, 5)))
    bias = rng.normal(size=(3, 4)).astype(np.float32)

    assert not weights.flags.c_contiguous and not inputs.flags.c_contiguous
    np.testing.assert_allclose(cpp.linear_batched(weights, inputs, bias), reference(weights, inputs, bias), rtol=1e-6)
    ints = (np.arange(24, dtype=np.int64).reshape(2, 3, 4), np.ones((2, 4), dtype=np.int64), np.zeros((2, 3), dtype=np.int64))
    np.testing.assert_allclose(cpp.linear_batched(*ints), reference(*ints))


@pytest.mark.parametrize(
    ("inputs_shape", "bias_shape"),
    [((3, 4), (2, 3)), ((2, 5), (2, 3)), ((2, 4), (1, 3)), ((2, 4), (2, 2))],
)
def test_mismatched_shapes_raise_instead_of_reading_past_a_buffer(inputs_shape, bias_shape):
    with pytest.raises(RuntimeError, match="does not match weights"):
        cpp.linear_batched(np.ones((2, 3, 4)), np.ones(inputs_shape), np.ones(bias_shape))


@pytest.mark.parametrize(
    ("weights", "inputs", "bias"),
    [(np.ones((3, 4)), np.ones((2, 4)), np.ones((2, 3))), (np.ones((2, 3, 4)), np.ones(4), np.ones((2, 3))), (np.ones((2, 3, 4)), np.ones((2, 4)), np.ones(3))],
)
def test_wrong_ranks_raise(weights, inputs, bias):
    with pytest.raises((ValueError, RuntimeError)):
        cpp.linear_batched(weights, inputs, bias)


def test_a_large_batch_matches():
    rng = np.random.default_rng(11)
    weights, inputs, bias = rng.normal(size=(64, 32, 48)), rng.normal(size=(64, 48)), rng.normal(size=(64, 32))

    np.testing.assert_allclose(cpp.linear_batched(weights, inputs, bias), reference(weights, inputs, bias), rtol=1e-10, atol=1e-10)
