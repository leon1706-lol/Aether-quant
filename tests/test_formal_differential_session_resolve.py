"""evaluation/forward_ledger.py's `resolve_session` against its Lean 4 model (formal/AetherFormal/SessionResolve.lean). A date is a number of days; here, days after 2020-01-01."""

from __future__ import annotations

import datetime

from aether_quant.formal import load_cases
from evaluation.forward_ledger import resolve_session

START = datetime.date(2020, 1, 1)


def _day(number: int) -> str:
    return (START + datetime.timedelta(days=int(number))).isoformat()


def test_python_matches_the_lean_model():
    cases = load_cases("session_resolve")["cases"]
    assert len(cases) >= 300
    for index, case in enumerate(cases):
        given = case["input"]
        sessions = [_day(number) for number in given["sessions"]]
        override = None if given["override"] is None else _day(given["override"])
        out = resolve_session(sessions, _day(given["now"]), override)
        expected = case["expected"]["session"]
        assert out == (None if expected is None else _day(expected)), (index, given)


def test_the_cases_cover_an_empty_calendar_an_override_and_a_future_only_calendar():
    cases = load_cases("session_resolve")["cases"]
    assert any(not case["input"]["sessions"] for case in cases)
    assert any(case["input"]["override"] is not None and case["expected"]["session"] is not None for case in cases)
    assert any(case["input"]["override"] is not None and case["expected"]["session"] is None for case in cases)
    assert any(case["input"]["override"] is None and case["input"]["sessions"] and case["expected"]["session"] is None for case in cases)
