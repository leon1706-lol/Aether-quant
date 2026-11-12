"""`execution.accounts.apply_risk_overrides` against its Lean model (formal/AetherFormal/AccountOverrides.lean, V6.6.5 #349):
an override is applied only when it tightens, on every generated case."""

from __future__ import annotations

from aether_quant.formal import load_cases, to_float
from execution.accounts import Account, apply_risk_overrides

KEYS = {"lower": "live.max_allowed_total_drawdown_pct", "higher": "risk.kill_switch.min_rolling_sharpe"}
MODES = {1: "observation", 2: "paper", 3: "live"}


def _tree(key: str, base: float | None) -> dict:
    tree: dict = {}
    if base is None:
        return tree
    node = tree
    parts = key.split(".")
    for part in parts[:-1]:
        node = node.setdefault(part, {})
    node[parts[-1]] = base
    return tree


def _read(tree: dict, key: str):
    node = tree
    for part in key.split("."):
        node = node[part]
    return node


def _apply(phase_v2: dict, account: Account):
    try:
        return apply_risk_overrides(phase_v2, account), False
    except ValueError:
        return None, True


def test_python_matches_the_lean_model():
    cases = load_cases("account_overrides")["cases"]
    assert len(cases) >= 300
    for index, case in enumerate(cases):
        given, expected = case["input"], case["expected"]
        if given["kind"] in KEYS:
            key = KEYS[given["kind"]]
            value = to_float(given["value"])
            out, refused = _apply(_tree(key, to_float(given["base"])), Account("x", risk_overrides={key: value}))
            assert refused == expected["refused"], (index, given)
            if not refused:
                assert abs(_read(out, key) - to_float(expected["value"])) < 1e-12, (index, given)
        elif given["kind"] == "flag":
            _, refused = _apply({"runtime": {"allow_live_orders": False}}, Account("x", risk_overrides={"runtime.allow_live_orders": given["value"]}))
            assert refused == expected["refused"], (index, given)
        else:
            out, refused = _apply({"runtime": {"mode": MODES[given["current"]]}}, Account("x", broker="coinbase", lean_environment="live-coinbase", mode=MODES[given["account"]]))
            assert refused == expected["refused"], (index, given)
            if not refused:
                assert out["runtime"]["mode"] == MODES[expected["mode"]], (index, given)


def test_the_cases_cover_every_kind_and_both_outcomes():
    cases = load_cases("account_overrides")["cases"]
    kinds = {case["input"]["kind"] for case in cases}
    assert kinds == {"lower", "higher", "flag", "mode"}
    for kind in kinds:
        outcomes = {case["expected"]["refused"] for case in cases if case["input"]["kind"] == kind}
        assert outcomes == {True, False}, kind
    assert any(case["input"].get("base") is None for case in cases if case["input"]["kind"] in KEYS)
