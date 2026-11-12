"""`monitoring.auth.authorize` against its Lean model (formal/AetherFormal/Authorize.lean, V6.6.5 #350)."""

from __future__ import annotations

from aether_quant.formal import load_cases
from monitoring.auth import Role, User, authorize


def test_python_matches_the_lean_model():
    cases = load_cases("authorize")["cases"]
    assert len(cases) >= 400
    for index, case in enumerate(cases):
        given = case["input"]
        user = None if given["anonymous"] else User("u", Role(given["role"]), "0" * 32, "0" * 64, ("*",) if given["all"] else tuple(given["accounts"]))
        granted = authorize(user, Role(given["required"]), given["account"], auth_required=given["auth_required"])
        assert granted == case["expected"]["granted"], (index, given)


def test_the_cases_cover_grants_refusals_and_anonymous_callers():
    cases = load_cases("authorize")["cases"]
    assert {case["expected"]["granted"] for case in cases} == {True, False}
    assert any(case["input"]["anonymous"] and case["expected"]["granted"] for case in cases)  # an open read
    assert any(case["input"]["anonymous"] and not case["expected"]["granted"] for case in cases)
    assert any(not case["input"]["all"] and not case["input"]["accounts"] for case in cases)
